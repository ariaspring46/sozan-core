"""Sozan phone support: SIP extension to local Persian voice on Vulkan1."""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time
from collections import deque
from pathlib import Path

from audio_codec import (
    PcmJitter,
    analyze_tx_pcm,
    chunk_pcm,
    decode_to_pcm16,
    encode_pcm16,
    gate_kind,
    pcm16_to_wav,
    pcm_similarity,
    rms,
    rtp_packet,
    rtp_parse,
)
from brain import (
    Brain,
    echo_should_block,
    is_ack,
    is_carrier_text,
    is_correction,
    is_done,
    is_hello,
    is_hold,
    is_howdy,
    is_repeat,
    is_social,
    is_stuck,
    is_who,
    tts_model,
    looks_like_echo,
    looks_like_speech,
    should_hold_fragment,
    worth_llm,
    wants_bye,
)
from meaning import INTENTS
from sales import (
    ADDRESS_LINE,
    BUY_LINE,
    BYE_LINE as SALES_BYE_LINE,
    CAMPAIGN_PATH,
    CLOSE_LINE,
    DECLINE_LINE,
    EXPLAIN,
    FALLBACK_LINE,
    FIXED_SALES_LINES,
    HELLO_LINE,
    HELLO_SMS_LINE,
    PAIN_LINE,
    FEATURE_LINES,
    MISHEARD_LINE,
    REPEAT_FREE,
    SALES_PROBE_LINE,
    WAIT_BRIGHT,
    WAIT_LINE as SALES_WAIT_LINE,
    ShopCard,
    SalesState,
    drop_repeats,
    extract_tags,
    fallback_line,
    finish_spoken,
    gift_line,
    guard_reply,
    load_campaign,
    mentions_address,
    note_spoken,
    plan_turn,
    read_signals,
    remember_dnc,
    sales_brief,
    sentence_done,
    sales_ended,
    sales_open,
    hello_for,
    value_for,
    value_kind_for,
    cached_sales_lines,
    too_alike,
    tool_followups,
    wait_line,
)
from sip import Call, SipUA, env_flag, normalize_dial

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("sozan.voice")

GREETING = "سلام، سوزانم."
HELLO_AGAIN = "جانم، گوش می‌کنم."
ACK_AFTER = "خب. هر جا گیر کردی بگو."
ACK_OPEN = "بگو ببینم گیرت کجاست."
ASK_AGAIN = "آخرش را دوباره می‌گی؟"
LISTEN = "گوش می‌کنم."
HOLD_LINE = "باشه، هستم."
WHO_LINE = "سوزانم. همین‌جا کنارتم."
DONE_LINE = "خوبه. اگر باز گیر کردی بگو."
STUCK_LINE = "بگو دقیقاً کجا گیر کرده."
CORRECT_LINE = "باشه. همون را یک جور دیگر بگو."
THINKING_LINES = (
    "یک لحظه صبر کن ببینم.",
    "بذار ببینم.",
    "صبر کن، دارم فکر می‌کنم.",
    "آها، یک لحظه.",
    "ببینم چی بهت بگم.",
    "یک ثانیه، تو ذهنم است.",
)
CURIOUS_LINES = (
    "هستی؟",
    "الو، هستی؟",
    "صدام می‌آد؟",
    "هنوز اونجایی؟",
    "جایی نرفتی؟",
    "داری گوش می‌دی؟",
)
CHECK_LINE = CURIOUS_LINES[0]
HOWDY_LINE = "خوبم. تو بگو."
BYE_LINE = "خداحافظ."
WAIT_LINE = THINKING_LINES[0]
THINK_WAIT_S = 1.8
NUDGE_AFTER_S = 5.0
SALES_HANG_AFTER_S = 6.0
ANSWER_SILENCE_S = 25.0
TX_KEEP = 10
SIM_ARM_S = 30.0
SIM_DIR = Path("/dev/shm/sozan-sim")


def hold_early_carrier(outbound: bool, heard_person: bool, age_s: float) -> bool:
    """Keep an outbound call up while the trunk plays its announcement."""
    return bool(outbound) and not heard_person and age_s < 20


def parse_sim_command(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if text.upper() == "SIM" or text.upper().startswith("SIM "):
        parts = text.split(maxsplit=2)
        instagram = parts[1].strip().lstrip("@") if len(parts) >= 2 else ""
        product = parts[2].strip() if len(parts) >= 3 else ""
        return instagram, product
    return "", ""


LIVE_LOG = Path.home() / "local-ai" / "sozan-voice-log" / "calls.jsonl"
LOG_CAP = 2_000_000


def append_turn_log(row: dict, path: Path | None = None) -> None:
    target = path or (LIVE_LOG if row.get("sim") is False else (SIM_DIR / "turns.jsonl"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == LIVE_LOG and target.is_file() and target.stat().st_size > LOG_CAP:
            rotated = target.with_suffix(".jsonl.1")
            if rotated.exists():
                rotated.unlink()
            target.rename(rotated)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("turn log write failed", exc_info=True)


def next_varied(pool: tuple[str, ...], index: int, last: str) -> tuple[str, int]:
    line = pool[index % len(pool)]
    index += 1
    if line == last and len(pool) > 1:
        line = pool[index % len(pool)]
        index += 1
    return line, index
ECHO_LIMIT = 5
FRAME = 320
PT = {"pcma": 8, "pcmu": 0}


def barge_kind_ready(hot_ms: int, kind: str, need_ms: int = 180) -> bool:
    return hot_ms >= need_ms and kind == "speech"


class RtpSession:
    def __init__(self, call: Call, port: int) -> None:
        self.call = call
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.settimeout(0.2)
        self.running = True
        self.playing = threading.Event()
        self.utterances: queue.Queue[bytes] = queue.Queue()
        self._play: queue.Queue[bytes | None] = queue.Queue()
        self._rx_buf = bytearray()
        self._speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._hot_ms = 0
        self._preroll = bytearray()
        self._barge = 0
        self.seq = 0
        self.ts = 0
        self.ssrc = int.from_bytes(os.urandom(4), "big")
        self.kind = call.rtp_payload if call.rtp_payload in PT else "pcma"
        self.pt = PT[self.kind]
        self._dest_lock = threading.Lock()
        self._dest = call.rtp_dest
        self.start_thresh = float(os.environ.get("VAD_START", "450"))
        self.barge_thresh = float(os.environ.get("BARGE_RMS", os.environ.get("VAD_START", "450")))
        self.barge_ms = int(os.environ.get("BARGE_MS", "420"))
        self.keep_thresh = float(os.environ.get("VAD_KEEP", "280"))
        self.silence_needed = int(os.environ.get("VAD_SILENCE_MS", "220"))
        self.commit_needed = int(os.environ.get("VAD_COMMIT_MS", "450"))
        self.max_speech_ms = int(os.environ.get("VAD_MAX_MS", "12000"))
        self.echo_corr = float(os.environ.get("ECHO_CORR", "0.55"))
        self._echo_until = 0.0
        self._tx_tail: deque[bytes] = deque(maxlen=40)
        self._tx_lock = threading.Lock()
        self.echo_hits = 0
        self.barge_off = False
        self.last_was_barge = False
        self._early_sent = False
        self.snapshots: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self.on_snapshot = None
        self._jitter = PcmJitter()
        self._tx_rec = bytearray()
        self._tx_rec_lock = threading.Lock()
        self._tx_dir: Path | None = None
        self._tx_path: Path | None = None
        threading.Thread(target=self._rx, name="rtp-rx", daemon=True).start()
        threading.Thread(target=self._tx, name="rtp-tx", daemon=True).start()

    def enable_tx_record(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._tx_dir = folder
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self._tx_path = folder / f"{stamp}-tx.wav"

    def close(self) -> None:
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        self._flush_tx_record()

    def _flush_tx_record(self) -> None:
        with self._tx_rec_lock:
            pcm = bytes(self._tx_rec)
            self._tx_rec.clear()
        path = self._tx_path
        folder = self._tx_dir
        self._tx_path = None
        if not pcm or path is None:
            return
        try:
            path.write_bytes(pcm16_to_wav(pcm, 8000))
        except OSError:
            log.warning("tx record write failed", exc_info=True)
            return
        stats = analyze_tx_pcm(pcm, 8000)
        log.info(
            "tx rec %s rms=%.0f peak=%s clips=%s gaps=%s ms=%s",
            path,
            stats["rms"],
            stats["peak"],
            stats["clips"],
            stats["gaps_300ms"],
            stats["ms"],
        )
        if folder is None:
            return
        kept = sorted(folder.glob("*-tx.wav"), key=lambda item: item.stat().st_mtime, reverse=True)
        for extra in kept[TX_KEEP:]:
            try:
                extra.unlink()
            except OSError:
                pass

    def play(self, pcm8k: bytes, end: bool = True) -> None:
        if pcm8k:
            for frame in chunk_pcm(pcm8k, FRAME):
                self._play.put(frame)
        if end:
            self._play.put(None)

    def _clear_play(self) -> None:
        try:
            while True:
                self._play.get_nowait()
        except queue.Empty:
            pass

    def wait_done(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.playing.is_set() and self._play.empty():
                return
            time.sleep(0.05)

    def _tx(self) -> None:
        next_at = time.monotonic()
        marker = True
        while self.running:
            frame = None
            try:
                frame = self._play.get_nowait()
            except queue.Empty:
                frame = b""
            if frame is None:
                self.playing.clear()
                self._echo_until = time.monotonic() + 0.4
                marker = True
                frame = b""
            elif frame:
                self.playing.set()
            else:
                if self._play.empty():
                    self.playing.clear()
            if frame == b"":
                payload = encode_pcm16(b"\x00" * FRAME, self.kind)
                mark = False
                if self.playing.is_set() and self._tx_rec:
                    with self._tx_rec_lock:
                        self._tx_rec.extend(b"\x00" * FRAME)
            else:
                with self._tx_lock:
                    self._tx_tail.append(frame)
                with self._tx_rec_lock:
                    self._tx_rec.extend(frame)
                payload = encode_pcm16(frame, self.kind)
                mark = marker
                marker = False
            packet = rtp_packet(self.seq, self.ts, self.ssrc, payload, marker=mark, pt=self.pt)
            self.seq = (self.seq + 1) & 0xFFFF
            self.ts = (self.ts + 160) & 0xFFFFFFFF
            with self._dest_lock:
                dest = self._dest
            if dest:
                try:
                    self.sock.sendto(packet, dest)
                except OSError:
                    pass
            next_at += 0.02
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.2:
                next_at = time.monotonic()

    def _rx(self) -> None:
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = rtp_parse(data)
            if not parsed:
                continue
            pt, seq, payload = parsed
            if pt == 101 or not payload:
                continue
            kind = "pcma" if pt == 8 else "pcmu" if pt == 0 else ""
            if not kind:
                continue
            with self._dest_lock:
                if self._dest is None or addr[0] == self.call.remote_addr[0] or addr[0] == "127.0.0.1":
                    self._dest = addr
            pcm = decode_to_pcm16(payload, kind)
            for frame in self._jitter.push(seq, pcm):
                self._on_pcm(frame)

    def _on_pcm(self, pcm: bytes) -> None:
        level = rms(pcm)
        if self.playing.is_set():
            self._remember(pcm)
            if self.barge_off:
                return
            if self._is_echo(pcm):
                self._barge = 0
                return
            if self._speech:
                self._interrupt()
                self._push(pcm, level)
                return
            if level >= self.barge_thresh:
                self._barge += 20
            else:
                self._barge = 0
            if not barge_kind_ready(self._barge, gate_kind(bytes(self._preroll)), self.barge_ms):
                if self._barge >= self.barge_ms:
                    self._barge = 0
                return
            self._interrupt()
            return
        self._barge = 0
        self._push(pcm, level)

    def _is_echo(self, pcm: bytes) -> bool:
        if not self._tx_tail:
            return False
        with self._tx_lock:
            tail = tuple(self._tx_tail)
        best = 0.0
        for tx in tail:
            score = pcm_similarity(pcm, tx)
            if score > best:
                best = score
        return best >= self.echo_corr

    def _remember(self, pcm: bytes) -> None:
        self._preroll.extend(pcm)
        if len(self._preroll) > 8000:
            del self._preroll[:-8000]

    def _interrupt(self) -> None:
        self._clear_play()
        self.playing.clear()
        self._echo_until = 0.0
        self._barge = 0
        if self._speech:
            return
        log.info("barge-in ms=%s", len(self._preroll) // 16)
        self.last_was_barge = True
        self._speech = True
        self._rx_buf = bytearray(self._preroll)
        self._speech_ms = len(self._preroll) // 16
        self._silence_ms = 0
        self._hot_ms = 0
        self._preroll.clear()

    def _push(self, pcm: bytes, level: float) -> None:
        if time.monotonic() < self._echo_until and not self._speech:
            self._preroll.clear()
            self._hot_ms = 0
            return
        if not self._speech:
            self._preroll.extend(pcm)
            if len(self._preroll) > 8000:
                del self._preroll[:-8000]
            if level >= self.start_thresh:
                self._hot_ms += 20
            else:
                self._hot_ms = 0
            if self._hot_ms >= 80:
                self._speech = True
                self._rx_buf = bytearray(self._preroll)
                self._speech_ms = self._hot_ms
                self._silence_ms = 0
                self._preroll.clear()
            return
        self._rx_buf.extend(pcm)
        self._speech_ms += 20
        if level < self.keep_thresh:
            self._silence_ms += 20
        else:
            self._silence_ms = 0
            self._early_sent = False
        if self._silence_ms >= self.silence_needed and self._speech_ms >= 240 and not self._early_sent:
            self._offer_snapshot()
            self._early_sent = True
        if (self._silence_ms >= self.commit_needed and self._speech_ms >= 240) or self._speech_ms >= self.max_speech_ms:
            utterance = bytes(self._rx_buf)
            gaps = self._jitter.gaps
            self._jitter.gaps = 0
            self._speech = False
            self._speech_ms = 0
            self._silence_ms = 0
            self._hot_ms = 0
            self._early_sent = False
            self._rx_buf.clear()
            log.info("utterance ms=%s gaps=%s barge=%s", len(utterance) // 16, gaps, self.last_was_barge)
            self.utterances.put(utterance)

    def _offer_snapshot(self) -> None:
        snap = bytes(self._rx_buf)
        if len(snap) < 16 * 400:
            return
        try:
            self.snapshots.put_nowait(snap)
        except queue.Full:
            try:
                self.snapshots.get_nowait()
            except queue.Empty:
                pass
            try:
                self.snapshots.put_nowait(snap)
            except queue.Full:
                pass
        hook = self.on_snapshot
        if hook:
            hook()

    def note_echo(self) -> None:
        self.echo_hits += 1
        if echo_should_block(self.echo_hits, ECHO_LIMIT):
            self.barge_off = True
            log.info("barge off after %s echo hits", self.echo_hits)

    def note_real_barge(self) -> None:
        self.echo_hits = 0


class Gateway:
    def __init__(self) -> None:
        self.brain = Brain()
        self.ua = SipUA(
            domain=os.environ.get("SIP_DOMAIN", "phone.telefonchy.com"),
            user=os.environ.get("SIP_USER", ""),
            password=os.environ.get("SIP_PASSWORD", ""),
            server_port=int(os.environ.get("SIP_PORT", "5060")),
            local_port=int(os.environ.get("LOCAL_SIP_PORT", "5062")),
            rtp_port=int(os.environ.get("LOCAL_RTP_PORT", "40000")),
            register=env_flag("SIP_REGISTER", True),
        )
        self.session: RtpSession | None = None
        self._session_lock = threading.Lock()
        self._call_generation = 0
        self.ua.on_call = self._start_call
        self.ua.on_hangup = self._end_call
        self.ua.on_dial_fail = self._dial_failed
        self._started_calls: set[str] = set()
        self._greet_pcm = b""
        self._clip_dir = Path.home() / "local-ai" / "sozan-voice-clips"
        self._voice: dict[str, bytes] = {}
        self._prefetching = threading.Event()
        self._helloed = False
        self._step = False
        self._last_kind = ""
        self._said: set[str] = set()
        self._last_line = GREETING
        self._last_alt = ""
        self._fragment = ""
        self._spoke_at = 0.0
        self._audio_at = 0.0
        self._checked_in = False
        self._heard_person = False
        self._outbound_call = False
        self._call_started = 0.0
        self._idle_since = 0.0
        self._think_i = 0
        self._nudge_i = 0
        self._nudge_count = 0
        self._campaign_file = CAMPAIGN_PATH if CAMPAIGN_PATH.is_file() else Path(__file__).with_name("campaign.json")
        self._campaign_mtime = 0.0
        self._campaign = {}
        self._reload_campaign()
        self._pending_sales: ShopCard | None = None
        self._peer_number = ""
        self._sales_card: ShopCard | None = None
        self._sales_brief = ""
        self._sales_state = ""
        self._sales: SalesState | None = None
        self._sales_pitched = False
        self._sales_said: set[str] = set()
        self._sales_greeted = False
        self._sales_cancel: threading.Event | None = None
        self._sales_turn_seq = 0
        self._outbound_pitch = False
        self._sim_until = 0.0
        self._sim_call = False
        self._sim_clip_dir = Path(os.environ.get("SIM_CLIP_DIR", "/dev/shm/sozan-sim/clips"))
        self._partial_lock = threading.Lock()
        self._partial_pcm = b""
        self._partial_text = ""
        self._partial_busy = False
        self._partial_done = False

    def _cache_voice(self) -> None:
        lines = [
            GREETING,
            HELLO_AGAIN,
            ACK_AFTER,
            ACK_OPEN,
            ASK_AGAIN,
            LISTEN,
            HOLD_LINE,
            WHO_LINE,
            DONE_LINE,
            STUCK_LINE,
            CORRECT_LINE,
            HOWDY_LINE,
            BYE_LINE,
            BUY_LINE,
            EXPLAIN,
            HELLO_LINE,
            HELLO_SMS_LINE,
            PAIN_LINE,
            *FEATURE_LINES,
            CLOSE_LINE,
            ADDRESS_LINE,
            FALLBACK_LINE,
            MISHEARD_LINE,
            SALES_PROBE_LINE,
            SALES_WAIT_LINE,
            *WAIT_BRIGHT,
            gift_line(),
            *THINKING_LINES,
            *CURIOUS_LINES,
        ]
        for intent in INTENTS:
            lines.append(intent.say)
            lines.append(intent.again)
        started = time.monotonic()
        cloud_lines = set(cached_sales_lines())
        for line in dict.fromkeys(lines):
            if not (line or "").strip():
                continue
            if line in cloud_lines and tts_model():
                pcm = self.brain.prefetch_cloud(line)
                if not pcm:
                    pcm, _ = self.brain.synthesize(line, cloud=False)
            else:
                pcm, _ = self.brain.synthesize(line, cloud=False)
            if pcm:
                self._voice[line] = pcm
        self._greet_pcm = self._voice.get(GREETING, self._greet_pcm)
        log.info("voice cache lines=%s seconds=%.2f", len(self._voice), time.monotonic() - started)

    def _save_clip(self, pcm: bytes, kind: str) -> None:
        folder = self._sim_clip_dir if self._sim_call else self._clip_dir
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        path = folder / f"{stamp}-{kind}.wav"
        path.write_bytes(pcm16_to_wav(pcm, 8000))
        log.info("clip %s", path)

    def prepare(self) -> None:
        log.info("waiting for voice model on Vulkan1")
        self.brain.wait_until_ready()
        self._cache_voice()
        if os.environ.get("SOZAN_SIM"):
            return
        try:
            self.brain.warm_meanings()
        except Exception:
            log.warning("support meanings unavailable", exc_info=True)
        try:
            self.brain.warm_chat()
        except Exception:
            log.warning("phone model warmup failed", exc_info=True)

    def serve(self) -> None:
        threading.Thread(target=self.ua.loop, name="sip", daemon=True).start()
        threading.Thread(target=self._control, name="dial", daemon=True).start()
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        while self.ua.running:
            time.sleep(0.5)

    def _control(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", int(os.environ.get("DIAL_PORT", "5072"))))
        server.listen(2)
        server.settimeout(0.5)
        log.info("dial control on 127.0.0.1:%s", os.environ.get("DIAL_PORT", "5072"))
        while self.ua.running:
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                raw = conn.recv(400).decode("utf-8", errors="replace").strip()
                if raw.upper() == "SIM" or raw.upper().startswith("SIM "):
                    reply = self._arm_sim(raw)
                    conn.send(f"{reply}\n".encode())
                    continue
                number = raw[5:].strip() if raw.upper().startswith("DIAL ") else raw
                if not self.brain.phone_ready():
                    log.warning("dial refused; phone model not ready")
                    conn.send(b"busy\n")
                    continue
                key = normalize_dial(number)
                self._peer_number = key
                self._reload_campaign()
                self._pending_sales = self._campaign.get(key)
                self._outbound_pitch = True
                greet = hello_for(self._pending_sales)
                self._prerender([greet, value_for(self._pending_sales)])
                brief = sales_brief(self._pending_sales) if self._pending_sales else sales_open()
                try:
                    self.brain.warm_sales(brief, greet)
                except Exception:
                    log.warning("sales warm on dial failed", exc_info=True)
                placed = self.ua.dial(number)
                if not placed:
                    self._pending_sales = None
                    self._outbound_pitch = False
                conn.send(f"{placed or 'busy'}\n".encode())

    def _prefetch_sales_lines(self) -> None:
        """Load or render the sales lines behind the call, so the caller's «الو» never waits on them. A line the cloud
        cannot make is skipped, not the rest: lines already on disk still load, and the voice's own breaker keeps a
        402 (no credit) to one request."""
        if self._prefetching.is_set():
            return
        self._prefetching.set()

        def run() -> None:
            try:
                for line in cached_sales_lines():
                    if line in self._voice:
                        continue
                    pcm = self.brain.prefetch_cloud(line)
                    if pcm:
                        self._voice[line] = pcm
            finally:
                self._prefetching.clear()

        threading.Thread(target=run, name="sozan-sales-prefetch", daemon=True).start()

    def _reload_campaign(self) -> None:
        """enrich_campaign.py rewrites the file between calls; pick up its profiles without a restart."""
        try:
            mtime = self._campaign_file.stat().st_mtime
        except OSError:
            return
        if mtime != self._campaign_mtime:
            self._campaign = load_campaign(self._campaign_file)
            self._campaign_mtime = mtime

    def _prerender(self, lines: list[str]) -> None:
        """Synthesize this call's personal lines while the phone rings, so the opening is not late."""

        def run() -> None:
            for line in lines:
                if not (line or "").strip() or line in self._voice:
                    continue
                try:
                    pcm = self.brain.prefetch_cloud(line) if tts_model() else b""
                    if not pcm:
                        pcm, _ = self.brain.synthesize(line, cloud=False)
                except Exception:
                    log.warning("prerender failed", exc_info=True)
                    continue
                if pcm:
                    self._voice[line] = pcm

        threading.Thread(target=run, name="sozan-prerender", daemon=True).start()

    def _arm_sim(self, raw: str) -> str:
        instagram, product = parse_sim_command(raw)
        self._pending_sales = ShopCard(instagram=instagram, product=product) if instagram else None
        self._outbound_pitch = True
        self._sim_until = time.monotonic() + SIM_ARM_S
        # Like DIAL: the card's own opening renders now, so the sim does not wait 8 s of Piper on «سلام».
        greet = hello_for(self._pending_sales)
        self._prerender([greet, value_for(self._pending_sales)])
        brief = sales_brief(self._pending_sales) if self._pending_sales else sales_open()
        try:
            self.brain.warm_sales(brief, greet)
        except Exception:
            log.warning("sales warm on sim failed", exc_info=True)
        log.info("sim armed seconds=%s instagram=%s", SIM_ARM_S, instagram or "-")
        return "armed"

    def _stop(self, *_args) -> None:
        log.info("stopping")
        self._end_call(self.ua.call)
        self.ua.stop()

    def _start_call(self, call: Call) -> None:
        if call.call_id in self._started_calls:
            return
        self._started_calls.add(call.call_id)
        with self._session_lock:
            if self.session:
                self.session.close()
            self.session = RtpSession(call, self.ua.rtp_port)
            session = self.session
            local = call.remote_addr[0] == "127.0.0.1"
            sim_armed = local and time.monotonic() < self._sim_until
            self._sim_call = sim_armed
            if sim_armed:
                self._sim_until = 0.0
            clip_dir = self._sim_clip_dir if self._sim_call else self._clip_dir
            session.enable_tx_record(clip_dir)
            self._call_generation += 1
            generation = self._call_generation
        card = self._pending_sales
        outbound = self._outbound_pitch or sim_armed
        self._pending_sales = None
        self._outbound_pitch = False
        self._sales_card = card
        self._sales_brief = sales_brief(card) if card else (sales_open() if outbound else "")
        self._sales_state = "live" if self._sales_brief else ""
        self._sales = (
            SalesState(
                sms_sent=bool(card and card.sms_sent),
                opening=hello_for(card),
                value_line=value_for(card),
                value_kind=value_kind_for(card),
            )
            if self._sales_state
            else None
        )
        self._sales_pitched = False
        self._sales_said = set()
        self._sales_greeted = False
        self._sales_cancel = None
        once = os.environ.pop("SOZAN_ONCE", "").strip()
        self._once_line = once
        if once:
            self._sales_state = ""
            self._sales_brief = ""
            self._sales = None
            log.info("once line armed")
        greet = hello_for(card) if self._sales_state else GREETING
        if self._sales_state:
            self.brain.start_sales(self._sales_brief, greet)
        else:
            self.brain.reset_dialog(greet)
        self._helloed = True
        self._step = False
        self._last_kind = "greet"
        self._said.clear()
        self._last_line = greet
        self._last_alt = ""
        self._fragment = ""
        self._spoke_at = time.monotonic()
        self._audio_at = self._spoke_at
        self._checked_in = False
        self._heard_person = False
        self._outbound_call = bool(outbound)
        self._call_started = time.monotonic()
        self._idle_since = 0.0
        self._think_i = 0
        self._nudge_i = 0
        self._nudge_count = 0
        with self._partial_lock:
            self._partial_pcm = b""
            self._partial_text = ""
            self._partial_busy = False
            self._partial_done = False
        opening = b"" if self._sales_state or self._once_line else (self._voice.get(greet) or self._greet_pcm)
        if opening:
            session.play(opening)
        session.on_snapshot = lambda sess=session: self._kick_partial(sess)
        if self._sales_state:
            log.info("sales call instagram=%s", card.instagram if card else "-")
        threading.Thread(
            target=self._converse,
            args=(session, generation),
            name="converse",
            daemon=True,
        ).start()

    def _end_call(self, _call: Call | None) -> None:
        with self._session_lock:
            self._call_generation += 1
            session = self.session
            self.session = None
        if session:
            session.close()
        self._started_calls.clear()
        self._sales_state = ""
        self._sales = None
        self._sales_card = None
        self._sim_call = False
        self._sales_brief = ""
        self._sales_pitched = False
        self._sales_said = set()
        self._sales_greeted = False
        if self._sales_cancel is not None:
            self._sales_cancel.set()
            self._sales_cancel = None
        self._outbound_pitch = False
        self._pending_sales = None
        self._peer_number = ""

    def _dial_failed(self, _number: str) -> None:
        self._pending_sales = None
        self._outbound_pitch = False
        self._peer_number = ""
        log.info("dial failed; sales pitch cleared")

    def _speak(self, session: RtpSession, generation: int, line: str, kind: str) -> None:
        pcm = self._voice.get(line)
        tts_s = 0.0
        if not pcm:
            pcm, tts_s = self.brain.synthesize(line)
        log.info("say kind=%s tts=%.2f line=%s", kind, tts_s, line)
        if pcm and generation == self._call_generation:
            session.play(pcm, end=True)
        self._last_kind = kind
        self._last_line = line
        self._spoke_at = time.monotonic()
        if kind == "meaning":
            self._step = True

    def _converse(self, session: RtpSession, generation: int) -> None:
        if self._once_line:
            self._speak(session, generation, self._once_line, "meaning")
            session.wait_done(12)
            self.ua.hangup()
            self._end_call(None)
            return
        if self._sales_state and tts_model():
            self._prefetch_sales_lines()
        deadline = time.monotonic() + 15 * 60
        while self.ua.running and time.monotonic() < deadline and generation == self._call_generation:
            try:
                utterance = session.utterances.get(timeout=0.15)
            except queue.Empty:
                self._kick_partial(session)
                self._check_in(session, generation)
                continue
            if generation != self._call_generation:
                break
            barged = session.last_was_barge
            session.last_was_barge = False
            self._audio_at = time.monotonic()
            utterance = self._coalesce(session, utterance)
            kind = gate_kind(utterance)
            threading.Thread(
                target=self._save_clip, args=(utterance, kind), name="clip", daemon=True
            ).start()
            if kind != "speech":
                log.info("gated kind=%s", kind)
                if barged:
                    session.note_echo()
                continue
            self._kick_partial(session)
            text, stt_s = self._transcribe_utterance(utterance)
            if is_social(text) or is_hello(text):
                heard = text
            else:
                heard = self.brain.clean_heard(text)
            if is_carrier_text(text) or is_carrier_text(heard):
                # An outbound trunk often answers at once and plays a network
                # announcement before the person picks up. Dropping on that
                # first snippet hangs up as they connect.
                early_outbound = hold_early_carrier(
                    self._outbound_call,
                    self._heard_person,
                    time.monotonic() - self._call_started,
                )
                if early_outbound:
                    log.info("carrier held outbound")
                    continue
                log.info("carrier hangup text=%s", heard or text)
                self._speak(session, generation, BYE_LINE, "bye")
                session.wait_done(4)
                self.ua.hangup()
                self._end_call(None)
                break
            if barged and looks_like_echo(heard, self._last_line):
                log.info("dropped echo text=%s", heard[:80])
                session.note_echo()
                continue
            if not looks_like_speech(heard) and not is_social(heard):
                log.info("dropped loop text=%s", heard[:80])
                if barged:
                    session.note_echo()
                continue
            if barged:
                session.note_real_barge()
            if is_social(heard):
                self._fragment = ""
            elif self._fragment:
                heard = f"{self._fragment} {heard}".strip()
                self._fragment = ""
            log.info("stt seconds=%.2f text=%s", stt_s, heard)
            self._checked_in = False
            self._nudge_count = 0
            self._idle_since = 0.0
            self._heard_person = True
            if self._turn(session, generation, heard, text):
                break
        if generation == self._call_generation and self.ua.call:
            log.info("call cap hangup")
            self.ua.hangup()
            self._end_call(None)

    def _kick_partial(self, session: RtpSession) -> None:
        try:
            snap = session.snapshots.get_nowait()
        except queue.Empty:
            return
        with self._partial_lock:
            if self._partial_busy:
                try:
                    session.snapshots.put_nowait(snap)
                except queue.Full:
                    pass
                return
            self._partial_busy = True
            self._partial_pcm = snap
            self._partial_text = ""
            self._partial_done = False

        def work() -> None:
            text, took = self.brain.transcribe(snap)
            with self._partial_lock:
                if self._partial_pcm is snap or self._partial_pcm == snap:
                    self._partial_text = text
                    self._partial_done = True
                self._partial_busy = False
            log.info("partial stt seconds=%.2f text=%s", took, (text or "")[:80])

        threading.Thread(target=work, name="stt-partial", daemon=True).start()

    def _transcribe_utterance(self, utterance: bytes) -> tuple[str, float]:
        started = time.monotonic()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with self._partial_lock:
                snap = self._partial_pcm
                done = self._partial_done
                busy = self._partial_busy
                text = self._partial_text
            extra = abs(len(utterance) - len(snap)) if snap else 10**9
            prefix = bool(snap) and utterance.startswith(snap)
            if not prefix:
                break
            if extra > 24000:
                break
            if done and text.strip() and extra <= 6400:
                log.info("used partial stt extra_ms=%s", extra // 16)
                return text, time.monotonic() - started
            if busy:
                time.sleep(0.05)
                continue
            break
        return self.brain.transcribe(utterance)

    def _think(self, session: RtpSession, generation: int, work) -> tuple[str, float]:
        started = time.monotonic()
        result: dict[str, tuple[str, float]] = {}

        def run() -> None:
            try:
                result["value"] = work()
            except Exception:
                log.warning("llm turn failed", exc_info=True)
                result["value"] = ("الان نرسید. یک لحظهٔ دیگر بگو.", 0.0)

        worker = threading.Thread(target=run, name="llm-turn", daemon=True)
        worker.start()
        worker.join(THINK_WAIT_S)
        if (
            worker.is_alive()
            and generation == self._call_generation
            and not session.playing.is_set()
            and session._play.empty()
            and not session._speech
            and self._last_kind != "wait"
        ):
            if self._sales_state:
                line = SALES_WAIT_LINE
            else:
                line, self._think_i = next_varied(THINKING_LINES, self._think_i, self._last_line)
            self._speak(session, generation, line, "wait")
        worker.join(4.0)
        if worker.is_alive():
            return "ببخشید، یه لحظه قطع شد. یه بار دیگه می‌فرمایید؟", time.monotonic() - started
        if self._sales_state:
            self._clear_snapshots(session)
        else:
            self._drain(session)
        return result.get("value", ("الان نرسید. یک لحظهٔ دیگر بگو.", 0.0))

    def _clear_snapshots(self, session: RtpSession) -> None:
        while True:
            try:
                session.snapshots.get_nowait()
            except queue.Empty:
                break

    def _pending_heard(self, session: RtpSession) -> str:
        parts: list[str] = []
        while True:
            try:
                clip = session.utterances.get_nowait()
            except queue.Empty:
                break
            if gate_kind(clip) != "speech":
                continue
            text, _took = self._transcribe_utterance(clip)
            heard = text if is_hello(text) or is_social(text) else self.brain.clean_heard(text)
            if is_carrier_text(heard) or not looks_like_speech(heard):
                continue
            parts.append(heard)
        return " ".join(parts).strip()

    def _drain(self, session: RtpSession) -> None:
        n = 0
        while True:
            try:
                session.utterances.get_nowait()
                n += 1
            except queue.Empty:
                break
        while True:
            try:
                session.snapshots.get_nowait()
            except queue.Empty:
                break
        if n:
            log.info("drained stale clips=%s", n)

    def _coalesce(self, session: RtpSession, first: bytes) -> bytes:
        parts = [first]
        total = len(first)
        cap = 12 * 8000 * 2
        while total < cap:
            try:
                nxt = session.utterances.get_nowait()
            except queue.Empty:
                break
            if gate_kind(nxt) != "speech":
                continue
            parts.append(nxt)
            total += len(nxt)
        if len(parts) > 1:
            log.info("coalesced clips=%s ms=%s", len(parts), total // 16)
        return b"".join(parts)

    def _hold_turn(self, session: RtpSession, heard: str) -> bool:
        if not session.utterances.qsize() or is_hello(heard) or wants_bye(heard):
            return False
        self._fragment = heard[-400:]
        log.info("holding open turn %s", heard[:80])
        return True

    def _check_in(self, session: RtpSession, generation: int) -> None:
        if session.playing.is_set() or session._speech:
            self._idle_since = 0.0
            return
        if self._sales_state:
            self._sales_idle(session, generation)
            return
        if self._last_kind not in {"meaning", "hello", "ack", "greet", "ask"}:
            return
        if self._nudge_count >= len(CURIOUS_LINES):
            return
        if not self._heard_person:
            return
        now = time.monotonic()
        if self._idle_since <= 0:
            self._idle_since = now
            return
        if now - self._idle_since < NUDGE_AFTER_S:
            return
        line, self._nudge_i = next_varied(CURIOUS_LINES, self._nudge_i, self._last_line)
        self._nudge_count += 1
        self._idle_since = 0.0
        self._speak(session, generation, line, "ask")

    def _sales_idle(self, session: RtpSession, generation: int) -> None:
        if self._sim_call:
            return
        now = time.monotonic()
        if not self._heard_person:
            if self._idle_since <= 0:
                self._idle_since = now
                return
            if now - self._idle_since < ANSWER_SILENCE_S:
                return
            self._speak(session, generation, BYE_LINE, "bye")
            session.wait_done(6)
            self.ua.hangup()
            self._end_call(None)
            return
        if self._last_kind not in {"meaning", "hello", "ack", "greet", "ask"}:
            return
        if self._nudge_count >= 2:
            return
        now = time.monotonic()
        if self._idle_since <= 0:
            self._idle_since = now
            return
        if self._nudge_count == 0:
            if now - self._idle_since < NUDGE_AFTER_S:
                return
            self._nudge_count = 1
            self._idle_since = now
            self._speak(session, generation, SALES_PROBE_LINE, "ask")
            return
        if now - self._idle_since < SALES_HANG_AFTER_S:
            return
        self._nudge_count = 2
        self._speak(session, generation, CLOSE_LINE, "bye")
        session.wait_done(8)
        self.ua.hangup()
        self._end_call(None)

    def _turn(self, session: RtpSession, generation: int, heard: str, text: str) -> bool:
        if self._hold_turn(session, heard):
            return False
        if self._sales_state:
            return self._sales_reply(session, generation, heard)
        if wants_bye(heard):
            self._speak(session, generation, BYE_LINE, "bye")
            session.wait_done(8)
            self.ua.hangup()
            self._end_call(None)
            return True
        if is_repeat(heard):
            self._speak(session, generation, self._last_line or GREETING, "ack")
            return False
        if is_hold(heard):
            self._speak(session, generation, HOLD_LINE, "ack")
            return False
        if is_who(heard):
            self._speak(session, generation, WHO_LINE, "hello")
            return False
        if is_done(heard):
            self._speak(session, generation, DONE_LINE, "ack")
            return False
        if is_stuck(heard):
            self._speak(session, generation, self._last_alt or STUCK_LINE, "meaning")
            return False
        if is_correction(heard):
            self._speak(session, generation, CORRECT_LINE, "ask")
            return False
        if is_howdy(heard):
            self._helloed = True
            self._speak(session, generation, HOWDY_LINE, "hello")
            return False
        if is_hello(heard):
            line = HELLO_AGAIN if self._helloed else GREETING
            self._helloed = True
            self._speak(session, generation, line, "hello")
            return False
        if is_ack(heard):
            if self._last_kind == "ask":
                self._speak(session, generation, LISTEN, "ask")
                return False
            line = ACK_AFTER if self._step else ACK_OPEN
            self._speak(session, generation, line, "ack" if self._step else "ask")
            return False
        meaning = self.brain.understand(heard)
        if meaning and generation == self._call_generation:
            line = meaning.again if meaning.name in self._said else meaning.say
            self._last_alt = meaning.say if line == meaning.again else meaning.again
            self._said.add(meaning.name)
            self._fragment = ""
            self._speak(session, generation, line, "meaning")
            return False
        words = [word for word in heard.split() if word]
        if should_hold_fragment(session.utterances.qsize(), len(words)):
            self._fragment = heard
            log.info("held fragment %s", heard)
            return False
        if self._hold_turn(session, heard):
            return False
        unsure = self.brain.last_score < 0.62
        if looks_like_speech(heard) and unsure and worth_llm(heard):
            answer, llm_s = self._think(session, generation, lambda: self.brain.reply(heard))
            log.info("turn llm=%.2f reply=%s", llm_s, answer)
            self._speak(session, generation, answer, "meaning")
            return False
        if self._last_kind == "ask":
            log.info("stayed quiet score=%.2f text=%s", self.brain.last_score, heard[:80])
            return False
        self._speak(session, generation, ASK_AGAIN, "ask")
        return False

    def _sales_reply(self, session: RtpSession, generation: int, heard: str) -> bool:
        return self._sales_speak(session, generation, heard)

    def _sales_speak(self, session: RtpSession, generation: int, heard: str) -> bool:
        state = self._sales
        if state is None:
            return False
        extra = self._pending_heard(session)
        if extra:
            heard = f"{heard} {extra}".strip()
        # The number is kept here: a caller who hangs up right after «زنگ نزنید» clears self._peer_number.
        peer = self._peer_number
        plan = plan_turn(state, heard)
        if plan.kind == "hold":
            log.info("sales holding for hello text=%s", heard[:80])
            self._log_sales_turn(heard, "hold", "", 0.0, 0.0, False, False)
            return False
        if plan.kind in {"hello", "close", "address", "fallback", "feature"}:
            return self._sales_fixed(session, generation, state, heard, plan, peer)
        started = time.monotonic()
        played_flag = {"on": False}
        self._sales_turn_seq += 1
        turn_seq = self._sales_turn_seq

        def filler() -> None:
            time.sleep(THINK_WAIT_S)
            if (
                not played_flag["on"]
                and turn_seq == self._sales_turn_seq
                and generation == self._call_generation
                and not session.playing.is_set()
                and session._play.empty()
                and not session._speech
                and self._last_kind != "wait"
            ):
                self._speak(session, generation, wait_line(heard), "wait")

        if self._last_kind != "wait":
            threading.Thread(target=filler, name="sales-wait", daemon=True).start()
        cancel = threading.Event()
        self._sales_cancel = cancel
        first_audio = 0.0
        generated: list[str] = []
        spoken_parts: list[str] = []
        raw_all = ""
        tags: set[str] = set()
        prompt_n = 0
        first_token_s = 0.0
        cost = 0.0
        model_name = ""
        played = False
        retry_heard = ""
        late_heard = ""
        gen = self.brain.sales_stream(plan.cue, cancel)
        try:
            for bit in self._ahead_sales(gen, cancel, generation):
                if generation != self._call_generation or cancel.is_set():
                    break
                extra = self._pending_heard(session)
                if extra or session._speech:
                    cancel.set()
                    retry_heard = f"{heard} {extra}".strip() if extra else heard
                    late_heard = extra
                    break
                sentence, raw_all, tags, spoken_parts, generated, played, first_audio, first_token_s, prompt_n = (
                    self._sales_play_bit(
                        session,
                        generation,
                        state,
                        heard,
                        bit,
                        generated,
                        spoken_parts,
                        played,
                        first_audio,
                        started,
                        played_flag,
                    )
                )
                prompt_n = int(bit.get("prompt_n") or prompt_n)
                first_token_s = float(bit.get("first_token_s") or first_token_s)
                cost = float(bit.get("cost") or cost)
                model_name = str(bit.get("model") or model_name)
        except Exception:
            log.warning("sales stream turn failed", exc_info=True)
        finally:
            gen.close()
        if retry_heard and not spoken_parts and generation == self._call_generation:
            heard = retry_heard
            late_heard = ""
            self.brain.pop_last_user()
            plan = plan_turn(state, heard)
            if plan.kind in {"hello", "close", "address", "fallback", "feature"}:
                # «...نه، زنگ نزنید» said while the model was thinking gets its own fixed line and DNC.
                session.play(b"", end=True)
                return self._sales_fixed(session, generation, state, heard, plan, peer)
            if plan.kind == "model":
                cancel = threading.Event()
                self._sales_cancel = cancel
                generated = []
                spoken_parts = []
                raw_all = ""
                tags = set()
                retry_gen = self.brain.sales_stream(plan.cue, cancel)
                try:
                    for bit in self._ahead_sales(retry_gen, cancel, generation):
                        sentence, raw_all, tags, spoken_parts, generated, played, first_audio, first_token_s, prompt_n = (
                            self._sales_play_bit(
                                session,
                                generation,
                                state,
                                heard,
                                bit,
                                generated,
                                spoken_parts,
                                played,
                                first_audio,
                                started,
                                played_flag,
                            )
                        )
                        prompt_n = int(bit.get("prompt_n") or prompt_n)
                        first_token_s = float(bit.get("first_token_s") or first_token_s)
                        cost = float(bit.get("cost") or cost)
                        model_name = str(bit.get("model") or model_name)
                except Exception:
                    log.warning("sales stream retry failed", exc_info=True)
                finally:
                    retry_gen.close()
        session.play(b"", end=True)
        if late_heard and late_echo(late_heard, spoken_parts):
            log.info("dropped echo text=%s", late_heard[:80])
            late_heard = ""
        generated_text = " ".join(generated).strip()
        spoken = " ".join(spoken_parts).strip()
        tags |= extract_tags(raw_all or generated_text)[1]
        if not spoken:
            spoken, more_tags = finish_spoken(raw_all or generated_text, state, heard)
            tags |= more_tags
            if spoken and not sentence_done(spoken):
                # A cut-off reply («عرض کنم که [پایان]») is never spoken.
                spoken = ""
            if spoken and not session._speech:
                self._speak_more(session, generation, spoken)
        refused = plan.signals.refuse or state.refused_cta
        offer_gift = (
            plan.allow_gift
            and not state.gifted
            and not refused
            and (plan.signals.price or plan.signals.later or "gift" in tags)
        )
        tool_lines, tool_end, tool_dnc = tool_followups(tags, state, heard, spoken)
        for extra in tool_lines:
            self._speak_more(session, generation, extra)
            spoken = f"{spoken} {extra}".strip()
        if tool_dnc:
            offer_gift = False
            remember_dnc(peer)
            log.info("sales outcome dnc")
        if not spoken and not offer_gift and (tool_end or "end" in tags):
            # A reply that is only [پایان] still ends the call: thanks for a refusal, else the closing line below.
            if refused:
                spoken = DECLINE_LINE
                self._speak(session, generation, spoken, "bye")
        elif not spoken and not offer_gift:
            spoken = fallback_line(state, heard)
            tags = set()
            self._speak(session, generation, spoken, "meaning")
        later_again = plan.signals.later and state.linked and not plan.signals.price
        if (
            (plan.signals.price or plan.signals.later)
            and not (tool_dnc or refused or later_again)
            and not mentions_address(spoken)
        ):
            extra = BUY_LINE
            self._speak_more(session, generation, extra)
            spoken = f"{spoken} {extra}".strip()
        if offer_gift:
            bonus = gift_line()
            if bonus and bonus not in spoken:
                self._speak_more(session, generation, bonus)
                spoken = f"{spoken} {bonus}".strip()
            state.gifted = True
        elif "gift" in tags:
            spoken = spoken.replace(gift_line(), "").strip()
        full_for_cache = (raw_all or generated_text or spoken).strip()
        self.brain.commit_assistant(full_for_cache)
        if session.last_was_barge and spoken_parts:
            state.interrupted = spoken_parts[0]
        note_spoken(state, spoken)
        took = time.monotonic() - started
        usage = getattr(self.brain, "last_usage", None) or {}
        if usage.get("cost"):
            cost = float(usage.get("cost") or 0)
        if usage.get("prompt"):
            prompt_n = int(usage.get("prompt") or prompt_n)
        hangup = plan.hangup or "end" in tags or tool_end or sales_ended(heard, spoken)
        log.info(
            "sales llm=%.2f first_token=%.2f first_audio=%.2f prompt_n=%s cost=%.6f model=%s kind=%s line=%s",
            took,
            first_token_s,
            first_audio,
            prompt_n,
            cost,
            model_name or "-",
            plan.kind,
            spoken,
        )
        self._log_sales_turn(
            heard, plan.kind, spoken, first_token_s, first_audio, state.gifted, hangup, cost, model_name
        )
        if spoken in FIXED_SALES_LINES:
            log.warning("sales model repeated a fixed line")
        self._last_kind = "meaning"
        self._last_line = spoken
        self._spoke_at = time.monotonic()
        if hangup:
            # A refusal or do-not-call ends with thanks, never one more pitch of the address;
            # an address already given this turn is not repeated by the closing line.
            if CLOSE_LINE not in spoken and not tool_dnc and not refused:
                closing = SALES_BYE_LINE if mentions_address(spoken) else CLOSE_LINE
                if not (closing == SALES_BYE_LINE and wants_bye(spoken)):
                    self._speak(session, generation, closing, "bye")
            if late_heard and read_signals(late_heard).wrong:
                remember_dnc(peer)
                log.info("sales outcome dnc")
            session.wait_done(8)
            self.ua.hangup()
            self._end_call(None)
            return True
        if late_heard and generation == self._call_generation:
            # Words said over the first sentence are the caller's next turn, not noise.
            return self._sales_speak(session, generation, late_heard)
        return False

    def _sales_fixed(
        self, session: RtpSession, generation: int, state: SalesState, heard: str, plan, peer: str
    ) -> bool:
        line = plan.line or (HELLO_LINE if plan.kind == "hello" else CLOSE_LINE)
        if plan.kind == "address":
            line = plan.line or ADDRESS_LINE
        if plan.kind == "fallback":
            line = plan.line or MISHEARD_LINE
        if plan.hangup and (plan.signals.wrong or plan.dnc):
            # Written before the goodbye plays: hanging up during it must not lose the request.
            remember_dnc(peer)
            log.info("sales outcome dnc")
        self.brain.commit_assistant(line)
        note_spoken(state, line)
        log.info("sales llm=0.00 kind=%s line=%s", plan.kind, line)
        self._log_sales_turn(heard, plan.kind, line, 0.0, 0.0, state.gifted, plan.hangup)
        self._speak(session, generation, line, "bye" if plan.hangup else "meaning")
        if plan.hangup and state.agreed:
            log.info("sales outcome interested")
        if plan.hangup:
            session.wait_done(8)
            self.ua.hangup()
            self._end_call(None)
            return True
        return False

    def _log_sales_turn(
        self,
        heard: str,
        kind: str,
        line: str,
        first_token: float,
        first_audio: float,
        gift: bool,
        hangup: bool,
        cost: float = 0.0,
        model_name: str = "",
    ) -> None:
        row = {
            "ts": time.time(),
            "heard": heard,
            "kind": kind,
            "line": line,
            "first_token": round(float(first_token or 0), 3),
            "first_audio": round(float(first_audio or 0), 3),
            "gift": bool(gift),
            "hangup": bool(hangup),
            "sim": self._sim_call,
            "cost": round(float(cost or 0), 6),
            "model": model_name,
        }
        log.info("sales turn %s", json.dumps(row, ensure_ascii=False))
        append_turn_log(row)

    def _sales_play_bit(
        self,
        session: RtpSession,
        generation: int,
        state: SalesState,
        heard: str,
        bit: dict,
        generated: list[str],
        spoken_parts: list[str],
        played: bool,
        first_audio: float,
        started: float,
        played_flag: dict[str, bool] | None = None,
    ) -> tuple[str, str, set[str], list[str], list[str], bool, float, float, int]:
        raw = str(bit.get("raw") or "")
        sentence = str(bit.get("sentence") or "").strip()
        text, tags = extract_tags(sentence)
        text = guard_reply(text, heard)
        if text and text not in REPEAT_FREE and any(too_alike(text, prev) for prev in state.said + spoken_parts):
            text = ""
        generated.append(sentence)
        if not text:
            return text, raw, tags, spoken_parts, generated, played, first_audio, float(bit.get("first_token_s") or 0), int(bit.get("prompt_n") or 0)
        if generation != self._call_generation or session._speech or session.last_was_barge:
            return text, raw, tags, spoken_parts, generated, played, first_audio, float(bit.get("first_token_s") or 0), int(bit.get("prompt_n") or 0)
        pcm = self._voice.get(text)
        tts_s = 0.0
        if not pcm:
            pcm, tts_s = self.brain.synthesize(text)
        if pcm and generation == self._call_generation:
            session.play(pcm, end=False)
            if played_flag is not None:
                played_flag["on"] = True
            if not played:
                first_audio = time.monotonic() - started
                played = True
            log.info("say kind=meaning tts=%.2f line=%s", tts_s, text)
        spoken_parts.append(text)
        return text, raw, tags, spoken_parts, generated, played, first_audio, float(bit.get("first_token_s") or 0), int(bit.get("prompt_n") or 0)

    def _ahead_sales(self, gen, cancel: threading.Event, generation: int):
        """Keep reading tokens while Piper builds the sentence already queued."""
        bits: queue.Queue = queue.Queue()
        done = threading.Event()

        def pump() -> None:
            try:
                for bit in gen:
                    if cancel.is_set() or generation != self._call_generation:
                        break
                    bits.put(bit)
            except Exception:
                log.warning("sales stream turn failed", exc_info=True)
            finally:
                bits.put(None)
                done.set()

        threading.Thread(target=pump, name="sales-tokens", daemon=True).start()
        try:
            while True:
                bit = bits.get()
                if bit is None:
                    break
                yield bit
        finally:
            cancel.set()
            done.wait(timeout=5)

    def _speak_more(self, session: RtpSession, generation: int, line: str) -> None:
        pcm = self._voice.get(line)
        tts_s = 0.0
        if not pcm:
            pcm, tts_s = self.brain.synthesize(line)
        log.info("say kind=gift tts=%.2f line=%s", tts_s, line)
        if pcm and generation == self._call_generation:
            session.play(pcm, end=False)
        self._last_line = line
        self._spoke_at = time.monotonic()


def late_echo(late: str, spoken_parts: list[str]) -> bool:
    """Words heard over a sentence that are mostly that sentence; a «درسته، ولی زنگ نزنید» over «درسته!» is the caller."""
    signals = read_signals(late)
    if signals.wrong or signals.refuse or signals.bye:
        return False
    for part in spoken_parts:
        said = len(part.split())
        if said >= 3 and looks_like_echo(late, part) and len(late.split()) <= said + 2:
            return True
    return False


def load_env_file() -> None:
    path = os.environ.get(
        "SOZAN_VOICE_ENV",
        os.path.expanduser("~/local-ai/config/sozan-voice.env"),
    )
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_env_file()
    if "--self-test" in sys.argv:
        brain = Brain()
        brain.wait_until_ready(30)
        phrase = "سلام، فروشگاه من ساخته نمی‌شود"
        pcm, tts_s = brain.synthesize(phrase)
        heard, stt_s = brain.transcribe(pcm)
        answer, llm_s = brain.reply(heard or phrase)
        print(f"tts_s={tts_s:.2f} stt_s={stt_s:.2f} heard={heard}")
        print(f"llm_s={llm_s:.2f} reply={answer}")
        if not pcm or not answer:
            raise SystemExit(1)
        return
    gateway = Gateway()
    gateway.prepare()
    log.info(
        "voice line user=%s domain=%s register=%s gpu=Vulkan1",
        gateway.ua.user,
        gateway.ua.domain,
        gateway.ua.register,
    )
    gateway.serve()


if __name__ == "__main__":
    main()
