"""Local SIP customer for sales-call experiments. Never dials the PSTN."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from audio_codec import decode_to_pcm16, encode_pcm16, match_rms_pcm16, resample_pcm16, rms, rtp_packet, rtp_parse
from brain import ffmpeg_bin
from sip import parse_message

ROOT = Path(__file__).resolve().parent
SIM_DIR = Path("/dev/shm/sozan-sim")
TURNS = SIM_DIR / "turns.jsonl"
RUNS = SIM_DIR / "runs.jsonl"
GW_SIP = int(os.environ.get("SIM_GW_SIP", "5064"))
GW_CTRL = int(os.environ.get("SIM_GW_CTRL", "5074"))
SIM_CTRL = int(os.environ.get("SIM_CTRL", "5075"))
SIM_SIP = int(os.environ.get("SIM_SIP", "5098"))
SIM_RTP = int(os.environ.get("SIM_RTP", "41012"))
PIPER = os.environ.get("PIPER_BIN", os.path.expanduser("~/.final-27b/bin/piper"))
ESPEAK = os.environ.get("ESPEAK_DATA", os.path.expanduser("~/.final-27b/bin/espeak-ng-data"))
MANA = os.environ.get("PIPER_MODEL", os.path.expanduser("~/.final-27b/models/tts/fa_IR-mana-medium.onnx"))
GYRO = os.path.expanduser("~/.final-27b/models/tts/fa_IR-gyro-medium.onnx")
FRAME = 320


def mix_shop_noise(frame: bytes, scale: int = 500) -> bytes:
    """Low shop-floor noise under the caller. Stays inside signed 16-bit."""
    if len(frame) < 2:
        return frame
    out = bytearray(frame)
    state = 0x1234567
    for i in range(0, len(out) - 1, 2):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        noise = (state % (scale * 2)) - scale
        sample = int.from_bytes(out[i : i + 2], "little", signed=True)
        mixed = max(-32768, min(32767, sample + noise))
        out[i : i + 2] = int(mixed).to_bytes(2, "little", signed=True)
    return bytes(out)


def _cmd(host: str, port: int, text: str, timeout: float = 20) -> str:
    sock = socket.create_connection((host, port), timeout=timeout)
    with sock:
        sock.sendall((text.strip() + "\n").encode("utf-8"))
        sock.settimeout(timeout)
        return sock.recv(8000).decode("utf-8", errors="replace").strip()


def arm_gateway(instagram: str = "", product: str = "") -> str:
    line = "SIM"
    if instagram:
        line += " " + instagram
        if product:
            line += " " + product
    return _cmd("127.0.0.1", GW_CTRL, line, timeout=30)


class CustomerCall:
    def __init__(self) -> None:
        self.sip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sip.bind(("127.0.0.1", SIM_SIP))
        self.sip.settimeout(0.4)
        self.rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtp.bind(("127.0.0.1", SIM_RTP))
        self.rtp.settimeout(0.05)
        self.call_id = ""
        self.branch = ""
        self.ok: dict | None = None
        self.remote_rtp: tuple[str, int] | None = None
        self.seq = 1
        self.ts = 0
        self.ssrc = int.from_bytes(os.urandom(4), "big")
        self.heard = bytearray()
        self.running = False
        self._rx_thread: threading.Thread | None = None
        self._sip_thread: threading.Thread | None = None
        self.gender = "f"
        self.noise = ""
        self._stt = None

    def _load_stt(self):
        if self._stt is not None:
            return self._stt
        root = os.environ.get("FAST_STT_DIR", os.path.expanduser("~/local-ai/models/stt/shenava"))
        py = os.environ.get("FAST_STT_PY", os.path.expanduser("~/local-ai/py"))
        if py and py not in sys.path:
            sys.path.insert(0, py)
        names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
        paths = [os.path.join(root, name) for name in names]
        if not all(os.path.isfile(path) for path in paths):
            return None
        import sherpa_onnx

        rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=paths[0],
            decoder=paths[1],
            joiner=paths[2],
            tokens=paths[3],
            num_threads=2,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
        self._stt = rec
        return rec

    def transcribe(self, pcm8k: bytes) -> str:
        rec = self._load_stt()
        if rec is None or not pcm8k:
            return ""
        import array

        up = resample_pcm16(pcm8k, 8000, 16000)
        samples = array.array("h")
        samples.frombytes(up[: len(up) - (len(up) % 2)])
        if not samples:
            return ""
        floats = array.array("f", (sample / 32768.0 for sample in samples))
        stream = rec.create_stream()
        stream.accept_waveform(16000, floats)
        rec.decode_stream(stream)
        return str(stream.result.text or "").strip()

    def synth(self, text: str) -> bytes:
        model = GYRO if self.gender == "m" else MANA
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.path.dirname(PIPER) + (
            ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
        )
        proc = subprocess.run(
            [PIPER, "--model", model, "--output_raw", "--espeak_data", ESPEAK, "--length_scale", "0.95", "-q"],
            input=text.encode("utf-8"),
            capture_output=True,
            env=env,
            timeout=20,
            check=False,
        )
        raw = proc.stdout or b""
        if not raw:
            return b""
        phone = resample_pcm16(raw, 22050, 8000)
        return match_rms_pcm16(phone, 7000.0, 30000.0)

    def _rx(self) -> None:
        while self.running:
            try:
                data, _addr = self.rtp.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = rtp_parse(data)
            if not parsed:
                continue
            pt, _seq, payload = parsed
            if pt != 8 or not payload:
                continue
            self.heard.extend(decode_to_pcm16(payload, "pcma"))

    def _wait_sip(self, seconds: float) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                data, _addr = self.sip.recvfrom(65535)
            except socket.timeout:
                continue
            msg = parse_message(data)
            if msg and msg["start"].startswith("SIP/2.0"):
                return msg
        raise TimeoutError("no sip response")

    def invite(self) -> None:
        self.call_id = secrets.token_hex(6)
        self.branch = "z9hG4bK" + secrets.token_hex(4)
        body = (
            "v=0\r\n"
            "o=- 1 1 IN IP4 127.0.0.1\r\n"
            "s=sim\r\n"
            "c=IN IP4 127.0.0.1\r\n"
            "t=0 0\r\n"
            f"m=audio {SIM_RTP} RTP/AVP 8\r\n"
            "a=rtpmap:8 PCMA/8000\r\n"
            "a=sendrecv\r\n"
            "a=ptime:20\r\n"
        )
        invite = (
            f"INVITE sip:673068@127.0.0.1 SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{SIM_SIP};branch={self.branch}\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:customer@127.0.0.1>;tag=cust\r\n"
            "To: <sip:673068@127.0.0.1>\r\n"
            f"Call-ID: {self.call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:customer@127.0.0.1:{SIM_SIP}>\r\n"
            "Content-Type: application/sdp\r\n"
            f"Content-Length: {len(body.encode())}\r\n"
            "\r\n"
            f"{body}"
        )
        self.sip.sendto(invite.encode(), ("127.0.0.1", GW_SIP))
        ok = None
        for _ in range(10):
            msg = self._wait_sip(3)
            code = msg["start"].split()[1]
            if code == "200":
                ok = msg
                break
        if not ok:
            raise RuntimeError("call was not answered")
        self.ok = ok
        ack = (
            f"ACK sip:673068@127.0.0.1:{GW_SIP} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{SIM_SIP};branch={self.branch}\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:customer@127.0.0.1>;tag=cust\r\n"
            f"To: {ok['headers']['to'][0]}\r\n"
            f"Call-ID: {self.call_id}\r\n"
            "CSeq: 1 ACK\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        self.sip.sendto(ack.encode(), ("127.0.0.1", GW_SIP))
        port = None
        for line in ok["body"].splitlines():
            if line.lower().startswith("m=audio "):
                port = int(line.split()[1])
        if port is None:
            raise RuntimeError("no audio port")
        self.remote_rtp = ("127.0.0.1", port)
        self.heard.clear()
        self.running = True
        self._rx_thread = threading.Thread(target=self._rx, name="sim-rtp", daemon=True)
        self._rx_thread.start()
        self._sip_thread = threading.Thread(target=self._sip_rx, name="sim-sip", daemon=True)
        self._sip_thread.start()

    def _sip_rx(self) -> None:
        while self.running:
            try:
                data, addr = self.sip.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = parse_message(data)
            if not msg:
                continue
            start = msg.get("start") or ""
            if start.startswith("BYE ") or start.startswith("BYE\t"):
                self._reply_200(msg, addr)
            elif "BYE" in start.split(" ", 1)[0]:
                self._reply_200(msg, addr)

    def _reply_200(self, msg: dict, addr: tuple[str, int]) -> None:
        via = (msg.get("headers") or {}).get("via", ["SIP/2.0/UDP 127.0.0.1"])[0]
        frm = (msg.get("headers") or {}).get("from", [""])[0]
        to = (msg.get("headers") or {}).get("to", [""])[0]
        cid = (msg.get("headers") or {}).get("call-id", [self.call_id])[0]
        cseq = (msg.get("headers") or {}).get("cseq", ["2 BYE"])[0]
        packet = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {frm}\r\n"
            f"To: {to}\r\n"
            f"Call-ID: {cid}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        try:
            self.sip.sendto(packet.encode(), addr)
        except OSError:
            pass

    def _play(self, pcm: bytes) -> None:
        if not self.remote_rtp:
            raise RuntimeError("no rtp")
        dest = self.remote_rtp
        frames = [pcm[i : i + FRAME] for i in range(0, max(0, len(pcm) - FRAME + 1), FRAME)]
        if not frames and pcm:
            frames = [pcm.ljust(FRAME, b"\x00")]
        for i, frame in enumerate(frames):
            if len(frame) < FRAME:
                frame = frame + b"\x00" * (FRAME - len(frame))
            if self.noise == "shop":
                frame = mix_shop_noise(frame)
            payload = encode_pcm16(frame, "pcma")
            self.rtp.sendto(
                rtp_packet(self.seq, self.ts, self.ssrc, payload, marker=i == 0, pt=8),
                dest,
            )
            self.seq = (self.seq + 1) & 0xFFFF
            self.ts = (self.ts + 160) & 0xFFFFFFFF
            time.sleep(0.02)
        silence = encode_pcm16(b"\x00" * FRAME, "pcma")
        for _ in range(45):
            self.rtp.sendto(rtp_packet(self.seq, self.ts, self.ssrc, silence, pt=8), dest)
            self.seq = (self.seq + 1) & 0xFFFF
            self.ts = (self.ts + 160) & 0xFFFFFFFF
            time.sleep(0.02)

    def _turns_len(self) -> int:
        if not TURNS.is_file():
            return 0
        return TURNS.stat().st_size

    def _latest_turn(self) -> dict:
        if not TURNS.is_file():
            return {}
        last = ""
        with TURNS.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return {}
        try:
            return json.loads(last)
        except json.JSONDecodeError:
            return {}

    def say(self, text: str, wait_s: float = 22.0) -> dict:
        before = self._turns_len()
        mark = len(self.heard)
        pcm = self.synth(text)
        started = time.monotonic()
        self._play(pcm)
        deadline = time.monotonic() + wait_s
        turn: dict = {}
        quiet_since = 0.0
        heard_speech = False
        turn_seen = False
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if not turn_seen:
                if self._turns_len() > before:
                    turn_seen = True
                    heard_speech = False
                    quiet_since = 0.0
                continue
            chunk = bytes(self.heard[mark:])
            if len(chunk) >= FRAME * 8:
                tail = chunk[-FRAME * 8 :]
                level = rms(tail)
                if level > 400:
                    heard_speech = True
                    quiet_since = 0.0
                elif heard_speech:
                    if quiet_since <= 0:
                        quiet_since = time.monotonic()
                    if time.monotonic() - quiet_since >= 0.9:
                        break
            elif heard_speech and quiet_since and time.monotonic() - quiet_since >= 0.9:
                break
        time.sleep(0.2)
        if self._turns_len() > before:
            turn = self._latest_turn()
        reply_pcm = bytes(self.heard[mark:])
        ear = self.transcribe(reply_pcm)
        took = time.monotonic() - started
        return {
            "said": text,
            "heard": turn.get("heard") or "",
            "line": turn.get("line") or "",
            "kind": turn.get("kind") or "",
            "ear": ear,
            "first_audio": turn.get("first_audio") or 0,
            "gift": turn.get("gift") or False,
            "hangup": turn.get("hangup") or False,
            "elapsed": round(took, 2),
            "reply_bytes": len(reply_pcm),
        }

    def bye(self) -> None:
        if not self.ok:
            return
        bye = (
            f"BYE sip:673068@127.0.0.1:{GW_SIP} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{SIM_SIP};branch={self.branch}\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:customer@127.0.0.1>;tag=cust\r\n"
            f"To: {self.ok['headers']['to'][0]}\r\n"
            f"Call-ID: {self.call_id}\r\n"
            "CSeq: 2 BYE\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        try:
            self.sip.sendto(bye.encode(), ("127.0.0.1", GW_SIP))
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        self.running = False
        try:
            self.sip.close()
        except OSError:
            pass
        try:
            self.rtp.close()
        except OSError:
            pass


SESSION: CustomerCall | None = None
PERSONA: dict = {}


def load_personas() -> dict[str, dict]:
    path = ROOT / "sim_personas.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


def handle(raw: str) -> str:
    global SESSION, PERSONA
    text = (raw or "").strip()
    if not text:
        return "empty"
    if text.upper().startswith("CALL"):
        name = text.split(maxsplit=1)[1].strip() if " " in text else ""
        personas = load_personas()
        PERSONA = personas.get(name) or {"id": name or "anon", "gender": "f", "instagram": "", "product": ""}
        if SESSION:
            SESSION.close()
        arm = arm_gateway(PERSONA.get("instagram") or "", PERSONA.get("product") or "")
        SESSION = CustomerCall()
        SESSION.gender = "m" if PERSONA.get("gender") == "m" else "f"
        SESSION.noise = PERSONA.get("noise") or ""
        SESSION.invite()
        return f"ok armed={arm} persona={PERSONA.get('id')}"
    if text.upper().startswith("SAY"):
        if SESSION is None:
            return "no-call"
        spoken = text[3:].strip()
        if len(spoken.split()) < 3 and spoken in {"سلام", "الو", "بله", "بفرمایید"}:
            spoken = "سلام وقتتون بخیر"
        row = SESSION.say(spoken)
        return json.dumps(row, ensure_ascii=False)
    if text.upper() in {"BYE", "HANGUP"}:
        if SESSION:
            SESSION.bye()
            SESSION = None
        return "bye"
    return "unknown"


def serve() -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", SIM_CTRL))
    server.listen(2)
    print(f"sim control 127.0.0.1:{SIM_CTRL}", flush=True)
    while True:
        conn, _addr = server.accept()
        with conn:
            raw = conn.recv(2000).decode("utf-8", errors="replace").strip()
            try:
                reply = handle(raw)
            except Exception as exc:
                reply = f"error {type(exc).__name__}: {exc}"
            conn.send((reply + "\n").encode("utf-8"))


def append_run(row: dict) -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
    elif len(sys.argv) > 1:
        print(_cmd("127.0.0.1", SIM_CTRL, " ".join(sys.argv[1:])))
    else:
        print("usage: sim_call.py serve | CALL id | SAY text | BYE")
