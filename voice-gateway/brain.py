"""Persian STT, Sozan reply, Persian TTS. STT/TTS are local subprocesses."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import array
import urllib.error
import urllib.parse
import urllib.request
import wave
from json import dumps, loads
from pathlib import Path

from audio_codec import (
    highpass_pcm16,
    limit_pcm16,
    lowpass_pcm16,
    match_rms_pcm16,
    pcm16_to_wav,
    presence_pcm16,
    resample_pcm16,
)

_FFMPEG_BIN = ""
from knowledge import SYSTEM_PROMPT
from meaning import INTENTS, PHONE_PHRASES, Meaning, MeaningIndex
from heard_bank import heard_rows, should_repair

log = logging.getLogger("sozan.voice.brain")

THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE = re.compile(r"```.*?```", re.DOTALL)
MARKDOWN = re.compile(r"[*_#>`]+")
JUNK = re.compile(
    r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SOUND|INAUDIBLE)[^\]]*\]|\((?:speaking|music|noise)[^)]*\)",
    re.IGNORECASE,
)
FA = re.compile(r"[\u0600-\u06FF]")
BYE = re.compile(
    r"خداحافظ|خدا حافظ|خدافه|فلحافظ|خداحاف|خحافظ|خدانگهدار|خدا نگهدار|باشه خدا(?:حافظ)?|ممنون خدا|مرسی خدا|فعلا|تمام|قطع کن"
)
_HELLO = ("سلام", "درود", "صبح بخیر", "عصر بخیر", "خوبی", "خوبید", "چطوری", "الو", "هلو", "هالو")
_ACK = {
    "باشه",
    "چشم",
    "ممنون",
    "مرسی",
    "آها",
    "اها",
    "اوکی",
    "خب",
    "درسته",
    "فهمیدم",
    "آره",
    "بله",
}


def chat_completions_url(url: str) -> str:
    root = (url or "").strip().rstrip("/")
    if not root:
        return ""
    if root.endswith("/chat/completions"):
        return root
    return root + "/chat/completions"


TTS_STYLE = "خانم، گرم، دوستانه و آرام، فروشندهٔ مؤدب، با مکث طبیعی؛ نه خبرخوان"


def cloud_speech_body(model: str, voice: str, text: str) -> dict:
    body: dict = {
        "model": model,
        "input": text,
        "response_format": "pcm",
        "provider": {"sort": "latency"},
    }
    if voice:
        body["voice"] = voice
    if model.startswith("google/"):
        body["provider"]["options"] = {
            "google-ai-studio": {"speech_metadata": {"style": TTS_STYLE}}
        }
    return body


def tts_model() -> str:
    return os.environ.get("TTS_MODEL", "").strip()


def tts_first_s() -> float:
    try:
        return float(os.environ.get("TTS_FIRST_S", "6"))
    except ValueError:
        return 6.0


def llm_is_local(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in {"127.0.0.1", "localhost"}


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_PHONE = re.compile(r"(?:\+98|0098|0)9\d{9}|\b9\d{9}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"\b(?:\d[ -]?){16}\b")


def mask_private(text: str) -> str:
    blob = _PHONE.sub("شماره", text or "")
    blob = _EMAIL.sub("ایمیل", blob)
    return _CARD.sub("کارت", blob)


def mask_messages(url: str, messages: list[dict]) -> list[dict]:
    if llm_is_local(url):
        return messages
    masked: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            content = mask_private(content)
        masked.append({**msg, "content": content})
    return masked


def _cache_system(model: str, messages: list[dict]) -> list[dict]:
    if "anthropic/" not in (model or "") and "claude" not in (model or ""):
        return messages
    out: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "system" and isinstance(content, str):
            out.append(
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )
        else:
            out.append(msg)
    return out


def sales_request_body(
    url: str,
    model: str,
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict:
    local = llm_is_local(url)
    body: dict = {
        "model": model,
        "messages": messages if local else _cache_system(model, messages),
        "temperature": 0.7 if local else 0.6,
        "max_tokens": 120 if local else 70,
        "stream": True,
        "stop": ["\n"],
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if local:
        body["cache_prompt"] = True
        body["id_slot"] = 0
        body["presence_penalty"] = 0.3
    else:
        body["provider"] = {"sort": "latency"}
        body["reasoning"] = {"effort": "none", "exclude": True}
        body["usage"] = {"include": True}
    return body


def open_llm(url: str, req: urllib.request.Request, timeout: float):
    if llm_is_local(url):
        return urllib.request.urlopen(req, timeout=timeout)
    return _DIRECT.open(req, timeout=timeout)


def _has_tool_tag(raw: str) -> bool:
    from sales import extract_tags

    return bool(extract_tags(raw)[1])


def speakable(text: str, sentences: int = 1) -> str:
    cleaned = THINK.sub("", text or "")
    cleaned = FENCE.sub("", cleaned)
    cleaned = MARKDOWN.sub("", cleaned)
    cleaned = cleaned.replace("\n", " ")
    cleaned = re.sub(r"[\u064b-\u0652\u0670\u0640]", "", cleaned)
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", cleaned)
    cleaned = cleaned.replace("app.sozan-core.ir", "اَپ نقطه سوزان، خط تیره، کُر، دات آی‌آر")
    cleaned = cleaned.replace("sozan-core.ir", "سوزان، خط تیره، کُر، دات آی‌آر")
    cleaned = re.sub(r"(?i)sozan-core", "سوزان، خط تیره، کُر", cleaned)
    cleaned = re.sub(r"(?i)(?<![A-Za-z])ir(?![A-Za-z])", "آی‌آر", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"(?i)instagram", "اینستاگرام", cleaned)
    cleaned = re.sub(r"(?i)این\s*stagram", "اینستاگرام", cleaned)
    cleaned = re.sub(r"(?i)telegram", "تلگرام", cleaned)
    cleaned = re.sub(r"(?i)whatsapp", "واتساپ", cleaned)
    cleaned = re.sub(r"(?i)website", "وبسایت", cleaned)
    cleaned = re.sub(r"(?i)\bok\b", "اوکی", cleaned)
    cleaned = re.sub(r"(?<![\u0600-\u06FF])اسمن(?![\u0600-\u06FF])", "اسمم", cleaned)
    cleaned = re.sub(r"[A-Za-z]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?؟])\s+", cleaned) if part.strip()]
    short = " ".join(parts[: max(1, sentences)])
    return short[:420]


def ffmpeg_bin() -> str:
    global _FFMPEG_BIN
    if _FFMPEG_BIN:
        return _FFMPEG_BIN
    explicit = os.environ.get("FFMPEG_BIN", "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        _FFMPEG_BIN = explicit
        return _FFMPEG_BIN
    local = os.path.expanduser("~/.local/bin/ffmpeg")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        _FFMPEG_BIN = local
        return _FFMPEG_BIN
    import shutil

    found = shutil.which("ffmpeg") or ""
    _FFMPEG_BIN = found
    return _FFMPEG_BIN


def phone_ffmpeg_filter(src_rate: int = 22050) -> str:
    pitch = float(os.environ.get("VOICE_PITCH", "1.0"))
    parts = ["highpass=f=110", "equalizer=f=2500:t=q:w=1.1:g=3"]
    if abs(pitch - 1.0) > 0.01:
        parts.append(f"rubberband=pitch={pitch:.3f}:formant=preserved:transients=smooth")
    parts.extend(
        [
            "acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=3",
            "alimiter=limit=0.93:attack=4:release=40",
            "aresample=8000:resampler=soxr",
        ]
    )
    return ",".join(parts)


def amplify_pcm16_ffmpeg(pcm: bytes, gain: float = 1.0, src_rate: int = 22050) -> bytes:
    ff = ffmpeg_bin()
    if not ff or not pcm:
        return b""
    filt = phone_ffmpeg_filter(src_rate)
    if abs(gain - 1.0) > 0.02:
        filt = f"volume={gain:.3f}," + filt
    try:
        proc = subprocess.run(
            [
                ff,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                str(src_rate),
                "-ac",
                "1",
                "-i",
                "pipe:0",
                "-af",
                filt,
                "-f",
                "s16le",
                "-ar",
                "8000",
                "-ac",
                "1",
                "pipe:1",
            ],
            input=pcm,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return b""
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[-200:]
        if err:
            log.warning("ffmpeg voice chain failed %s", err)
        return b""
    return proc.stdout


def amplify_pcm16_python(pcm: bytes, gain: float = 1.0, src_rate: int = 22050) -> bytes:
    extra = float(os.environ.get("VOICE_PRESENCE_DB", "5"))
    target = float(os.environ.get("VOICE_RMS", "7300"))
    ceiling = 30000.0
    if not pcm:
        return pcm
    shaped = highpass_pcm16(pcm, src_rate, 250)
    shaped = presence_pcm16(shaped, src_rate, 1200, 3200, extra)
    shaped = lowpass_pcm16(shaped, src_rate, 3400)
    phone = resample_pcm16(shaped, src_rate, 8000) if src_rate != 8000 else shaped
    phone = match_rms_pcm16(phone, target, ceiling)
    if abs(gain - 1.0) > 0.02:
        phone = limit_pcm16(phone, gain, ceiling)
    return phone


def amplify_pcm16(pcm: bytes, gain: float | None = None, src_rate: int = 22050) -> bytes:
    """Telephone-band speech: ffmpeg soxr by default, Python chain as fallback."""
    level = gain if gain is not None else float(os.environ.get("VOICE_GAIN", "1.0"))
    if not pcm:
        return pcm
    chain = os.environ.get("VOICE_CHAIN", "ffmpeg").strip().lower()
    if chain != "python":
        out = amplify_pcm16_ffmpeg(pcm, level, src_rate)
        if out:
            return out
    return amplify_pcm16_python(pcm, level, src_rate)


def piper_voice_args() -> list[str]:
    return [
        "--length_scale",
        os.environ.get("PIPER_LENGTH", "0.95"),
        "--noise_scale",
        os.environ.get("PIPER_NOISE", "0.667"),
        "--noise_w",
        os.environ.get("PIPER_NOISE_W", "0.8"),
        "--sentence_silence",
        "0.08",
        "-q",
    ]


REPEAT = re.compile(r"(.)\1{4,}")


def looks_like_speech(text: str) -> bool:
    blob = JUNK.sub("", text or "").strip(" .\n\t،؟?!-")
    blob = REPEAT.sub("", blob).strip()
    if len(blob) < 2:
        return False
    words = [word for word in re.split(r"\s+", blob) if word]
    if len(words) >= 4 and len(set(words)) / len(words) < 0.45:
        return False
    letters = FA.findall(blob)
    if len(letters) >= 8 and len(set(letters)) <= 4:
        return False
    if len(letters) >= 12:
        most = max(letters.count(letter) for letter in set(letters))
        if most / len(letters) >= 0.35:
            return False
    if len(letters) >= 3 and len(set(letters)) >= 3:
        return True
    return False


_FIXES = (
    ("داروالت", "درباره"),
    ("سودان", "سوزان"),
        ("سوزون", "سوزان"),
        ("روزان", "سوزان"),
    ("دواره", "دوباره"),
    ("توزی", "توضیح"),
    ("تازی", "توضیح"),
)
_NOISE = ("موسیقی", "موزیک", "آهنگ", "زیرنویس", "تماشا", "لایک", "اشتراک")
_STEMS = ("سوزان", "فروش", "دامنه", "پنل", "ورود", "ساخت", "بساز", "سفارش", "سایت")


def clarify(text: str) -> str:
    cleaned = text or ""
    for wrong, right in _FIXES:
        cleaned = cleaned.replace(wrong, right)
    return cleaned


def usable_request(text: str) -> bool:
    if not looks_like_speech(text):
        return False
    cleaned = clarify(text)
    has_stem = any(stem in cleaned for stem in _STEMS)
    if any(noise in cleaned for noise in _NOISE) and not has_stem:
        return False
    return has_stem


def worth_llm(text: str) -> bool:
    if usable_request(text):
        return True
    cleaned = clarify(text)
    letters = FA.findall(cleaned)
    words = [word for word in cleaned.split() if word]
    return looks_like_speech(cleaned) and len(letters) >= 8 and len(words) >= 2


def is_carrier_text(text: str) -> bool:
    cleaned = text or ""
    if any(word in cleaned for word in ("موسیقی", "موزیک", "آهنگ")):
        return True
    latin = re.sub(r"[^A-Za-z]+", " ", cleaned).strip()
    persian = FA.findall(cleaned)
    if latin and len(persian) < 3 and not re.search(r"(?i)\b(allo|hello|hallo|hi|ok)\b", latin):
        return True
    return any(
        part in cleaned
        for part in (
            "پاسخگویی",
            "مشترک مورد",
            "در دسترس نیست",
            "لطفا بعدا",
            "لطفاً بعدا",
            "منتظر بمانید",
            "مخاطب",
            "در دسترس",
            "نمی باشد",
            "نمی‌باشد",
            "شماره گیری",
            "شماره‌گیری",
            "اعلام می گردد",
            "اعلام می‌گردد",
        )
    )


def wants_bye(text: str) -> bool:
    blob = text or ""
    if re.search(r"آقای حافظ|خانم حافظ", blob):
        return False
    return bool(BYE.search(blob))


def _plain(text: str) -> str:
    blob = re.sub(r"[^\u0600-\u06FFA-Za-z\s]", " ", clarify(text or ""))
    return re.sub(r"\s+", " ", blob).strip()


def is_hello(text: str) -> bool:
    blob = _plain(text)
    if not blob:
        return False
    blob = re.sub(r"(?i)\b(allo|hello|hallo|alo)\b", "الو", blob)
    if any(stem in blob for stem in _STEMS):
        return False
    if not any(word in blob for word in _HELLO):
        return False
    leftover = blob
    for word in _HELLO:
        leftover = leftover.replace(word, " ")
    leftover = leftover.replace("من", " ").replace("هستم", " ")
    leftover = re.sub(r"\s+", " ", leftover).strip()
    words = [word for word in blob.split() if word]
    first_is_hello = bool(words) and any(words[0] == word or words[0].endswith(word) for word in _HELLO)
    return len(leftover) <= 2 or (first_is_hello and len(words) <= 5)


def is_ack(text: str) -> bool:
    words = [word for word in _plain(text).split() if word]
    return bool(words) and all(word in _ACK for word in words)


def is_repeat(text: str) -> bool:
    blob = _plain(text)
    if any(stem in blob for stem in _STEMS):
        return False
    if blob in {"چی", "ها", "چی گفتی", "چه گفتی"}:
        return True
    return any(
        part in blob
        for part in ("چی گفتی", "چه گفتی", "نشنیدم", "متوجه نشدم", "دوباره بگو", "دوباره می‌گی", "یک بار دیگه")
    )


def is_hold(text: str) -> bool:
    blob = _plain(text)
    if any(stem in blob for stem in _STEMS) or len(blob.split()) > 4:
        return False
    return any(part in blob for part in ("صبر کن", "یه لحظه", "یک لحظه", "وایسا"))


def is_who(text: str) -> bool:
    blob = _plain(text)
    if any(stem in blob for stem in _STEMS):
        return False
    return any(part in blob for part in ("کی هستی", "کی هستین", "اسمت چیه", "اسم شما", "شما کی"))


def is_howdy(text: str) -> bool:
    blob = _plain(text)
    if any(stem in blob for stem in _STEMS) or len(blob.split()) > 6:
        return False
    return any(part in blob for part in ("حالت خوب", "حالت چطور", "چه خبر", "چطوری", "خوبی", "خوبید"))


def is_done(text: str) -> bool:
    blob = _plain(text)
    return len(blob.split()) <= 8 and any(part in blob for part in ("درست شد", "حل شد", "اوکی شد"))


def is_stuck(text: str) -> bool:
    blob = _plain(text)
    return any(part in blob for part in ("فایده نداشت", "باز هم نشد", "بازم نشد", "عوض نشد", "همون جور موند"))


def is_correction(text: str) -> bool:
    return _plain(text) in {"نه", "نه نه", "اشتباه", "اشتباهه", "اشتباه گفتی", "منظورم این نبود"}


def is_social(text: str) -> bool:
    return any(
        check(text)
        for check in (wants_bye, is_repeat, is_hold, is_who, is_done, is_stuck, is_correction, is_hello, is_howdy, is_ack)
    )


def looks_like_echo(heard: str, last_line: str) -> bool:
    blob = (heard or "").strip()
    if not blob:
        return True
    if is_carrier_text(blob):
        return True
    spoken = _plain(last_line)
    got = _plain(blob)
    if spoken and (spoken in got or got in spoken):
        return True
    return False


def should_hold_fragment(waiting: int, word_count: int) -> bool:
    return waiting > 0 and word_count <= 3


def echo_should_block(hits: int, limit: int = 5) -> bool:
    return hits >= limit


def _read_wav_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as fh:
        rate = fh.getframerate()
        frames = fh.readframes(fh.getnframes())
        width = fh.getsampwidth()
        channels = fh.getnchannels()
    if width != 2:
        return b"", rate
    if channels <= 1:
        return frames, rate
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    mono = array.array("h")
    for i in range(0, len(samples) - channels + 1, channels):
        mono.append(int(sum(samples[i : i + channels]) / channels))
    return mono.tobytes(), rate


class PiperWorker:
    def __init__(self, piper_bin: str, piper_model: str, espeak_data: str) -> None:
        self.piper_bin = piper_bin
        self.piper_model = piper_model
        self.espeak_data = espeak_data
        root = os.environ.get("PIPER_SHM", "/dev/shm/sozan-tts")
        self.dir = Path(root)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.dir = Path("/tmp/sozan-tts")
            self.dir.mkdir(parents=True, exist_ok=True)
        self.proc: subprocess.Popen[bytes] | None = None
        self.lock = threading.Lock()
        self._seq = 0
        self._start()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        lib = os.path.dirname(self.piper_bin)
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        return env

    def _start(self) -> None:
        self.close()
        try:
            self.proc = subprocess.Popen(
                [
                    self.piper_bin,
                    "--model",
                    self.piper_model,
                    "--json-input",
                    "--output_dir",
                    str(self.dir),
                    "--espeak_data",
                    self.espeak_data,
                    *piper_voice_args(),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._env(),
            )
        except Exception:
            log.warning("piper worker failed to start", exc_info=True)
            self.proc = None

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def synth_raw(self, text: str) -> bytes:
        spoken = (text or "").strip()
        if not spoken:
            return b""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            proc = self.proc
            if proc is None or proc.stdin is None:
                raise RuntimeError("piper worker down")
            self._seq += 1
            path = self.dir / f"t{os.getpid()}-{self._seq}.wav"
            try:
                path.unlink()
            except OSError:
                pass
            line = dumps({"text": spoken, "output_file": str(path)}, ensure_ascii=False) + "\n"
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
            deadline = time.monotonic() + 8
            last_size = -1
            while time.monotonic() < deadline:
                if path.is_file():
                    size = path.stat().st_size
                    if size > 64 and size == last_size:
                        pcm, rate = _read_wav_pcm(path)
                        try:
                            path.unlink()
                        except OSError:
                            pass
                        if not pcm:
                            raise RuntimeError("piper empty wav")
                        if rate != 22050:
                            pcm = resample_pcm16(pcm, rate, 22050)
                        return pcm
                    last_size = size
                time.sleep(0.02)
            raise TimeoutError("piper json timeout")


class Brain:
    def __init__(self) -> None:
        self.whisper_bin = os.environ.get(
            "WHISPER_BIN", os.path.expanduser("~/.final-27b/bin/whisper-cli")
        )
        self.whisper_lib = os.environ.get(
            "WHISPER_LIB", os.path.expanduser("~/.final-27b/opt/whisper")
        )
        self.whisper_model = os.environ.get(
            "WHISPER_MODEL", os.path.expanduser("~/.final-27b/models/stt/ggml-base.bin")
        )
        self.piper_bin = os.environ.get("PIPER_BIN", os.path.expanduser("~/.final-27b/bin/piper"))
        self.piper_model = os.environ.get(
            "PIPER_MODEL", os.path.expanduser("~/.final-27b/models/tts/fa_IR-gyro-medium.onnx")
        )
        self.espeak_data = os.environ.get(
            "ESPEAK_DATA", os.path.expanduser("~/.final-27b/bin/espeak-ng-data")
        )
        self.llm_url = chat_completions_url(
            os.environ.get("LLM_URL", "http://127.0.0.1:19292/v1")
        )
        self.llm_model = os.environ.get("LLM_MODEL", "ornith-phone")
        self.llm_fallback_url = chat_completions_url(
            os.environ.get("LLM_FALLBACK_URL", "http://127.0.0.1:19292/v1")
        )
        self.llm_fallback_model = os.environ.get("LLM_FALLBACK_MODEL", "ornith-phone")
        self.embed_url = os.environ.get("EMBED_URL", "http://127.0.0.1:19292/v1/embeddings")
        self.embed_model = os.environ.get("EMBED_MODEL", "bge-m3")
        self.embed_min = float(os.environ.get("EMBED_MIN", "0.62"))
        self.last_score = 0.0
        self.history: list[dict[str, str]] = []
        self.sales_system = ""
        self.last_sales_stats: dict[str, float | int] = {}
        self.last_usage: dict[str, float | int] = {}
        self._meanings: MeaningIndex | None = None
        self._phrases: MeaningIndex | None = None
        self._stt_lock = threading.Lock()
        self._fast_stt = self._load_fast_stt()
        self.phrase_min = float(os.environ.get("PHRASE_MIN", "0.72"))
        self.piper = PiperWorker(self.piper_bin, self.piper_model, self.espeak_data)

    def health(self) -> bool:
        root = self.llm_url.split("/v1/")[0]
        try:
            with urllib.request.urlopen(root + "/health", timeout=3) as res:
                return res.status == 200
        except Exception:
            return False

    def phone_ready(self) -> bool:
        if not llm_is_local(self.llm_url):
            return True
        if not self.health():
            return False
        root = self.llm_url.split("/v1/")[0]
        try:
            with urllib.request.urlopen(root + "/running", timeout=3) as res:
                rows = loads(res.read().decode()).get("running") or []
        except Exception:
            return False
        return any(str(row.get("model") or "") == self.llm_model for row in rows)

    def wait_until_ready(self, timeout: float = 180) -> None:
        if not llm_is_local(self.llm_url):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.health():
                return
            time.sleep(1.5)
        raise TimeoutError("voice model did not become ready")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        payload = dumps({"model": self.embed_model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            self.embed_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            body = loads(res.read().decode("utf-8"))
        rows: list[list[float] | None] = [None] * len(texts)
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            index = int(item.get("index") or 0)
            vector = item.get("embedding")
            if isinstance(vector, list) and 0 <= index < len(rows):
                rows[index] = [float(value) for value in vector]
        if any(row is None for row in rows):
            raise RuntimeError("embed incomplete")
        return [row for row in rows if row is not None]

    def warm_meanings(self) -> None:
        samples: list[str] = []
        labels: list[tuple[str, str, str]] = []
        for intent in INTENTS:
            for sample in intent.samples:
                samples.append(sample)
                labels.append((intent.name, intent.say, intent.again))
        phrase_samples: list[str] = []
        phrase_labels: list[str] = []
        for canonical, variants in PHONE_PHRASES:
            for sample in variants:
                phrase_samples.append(sample)
                phrase_labels.append(canonical)
        for canonical, train, _holdout in heard_rows():
            for sample in train:
                phrase_samples.append(sample)
                phrase_labels.append(canonical)
        vectors = []
        batch = samples + phrase_samples
        for start in range(0, len(batch), 48):
            vectors.extend(self._embed(batch[start : start + 48]))
        index = MeaningIndex()
        for (name, say, again), vector in zip(labels, vectors[: len(samples)]):
            index.add(name, say, vector, again)
        self._meanings = index
        phrases = MeaningIndex()
        for canonical, vector in zip(phrase_labels, vectors[len(samples) :]):
            phrases.add_phrase(canonical, vector)
        self._phrases = phrases
        log.info(
            "support meanings ready samples=%s phrases=%s",
            len(samples),
            len(phrase_samples),
        )

    def clean_heard(self, text: str) -> str:
        cleaned = clarify(text)
        if self._phrases is None or not cleaned.strip():
            return cleaned
        try:
            vector = self._embed([cleaned[:500]])[0]
        except Exception:
            log.warning("phrase embed failed", exc_info=True)
            return cleaned
        hit = self._phrases.best(vector)
        if hit is None or not should_repair(cleaned, hit.name, hit.score, self.phrase_min):
            return cleaned
        log.info("phrase canonical=%s score=%.2f from=%s", hit.name, hit.score, cleaned[:80])
        return hit.name

    def understand(self, text: str) -> Meaning | None:
        self.last_score = 0.0
        if self._meanings is None or not (text or "").strip():
            return None
        try:
            vector = self._embed([text[:500]])[0]
        except Exception:
            log.warning("embed failed", exc_info=True)
            return None
        hit = self._meanings.best(vector)
        if hit is None:
            return None
        self.last_score = hit.score
        log.info("embed intent=%s score=%.2f", hit.name, hit.score)
        if hit.score < self.embed_min:
            return None
        return hit

    def warm_chat(self) -> None:
        if not llm_is_local(self.llm_url):
            return
        payload = dumps(
            {
                "model": self.llm_model,
                "messages": [{"role": "user", "content": "یک سلام کوتاه بگو."}],
                "temperature": 0.4,
                "max_tokens": 80,
                "chat_template_kwargs": {"reasoning_effort": "low"},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.llm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as res:
            body = loads(res.read().decode("utf-8"))
        message = ((body.get("choices") or [{}])[0].get("message") or {})
        text = str(message.get("content") or "")[:80]
        log.info("phone model warm %s", text or "empty")

    def reset_dialog(self, greeting: str) -> None:
        self.history = [{"role": "assistant", "content": greeting}]

    def start_sales(self, system: str, greeting: str) -> None:
        self.sales_system = system
        self.history = [{"role": "assistant", "content": greeting}]

    def commit_assistant(self, spoken: str) -> None:
        text = (spoken or "").strip()
        if not text:
            return
        self.history.append({"role": "assistant", "content": text})

    def pop_last_user(self) -> None:
        if self.history and self.history[-1].get("role") == "user":
            self.history.pop()

    def warm_sales(self, system: str, greeting: str) -> None:
        self.start_sales(system, greeting)
        messages = mask_messages(
            self.llm_url,
            [
                {"role": "system", "content": system},
                {"role": "assistant", "content": greeting},
            ],
        )
        payload = dumps(
            sales_request_body(self.llm_url, self.llm_model, messages, max_tokens=1, temperature=0.0)
        ).encode("utf-8")
        req = urllib.request.Request(
            self.llm_url,
            data=payload,
            headers=self._sales_headers(self.llm_url),
            method="POST",
        )
        try:
            with open_llm(self.llm_url, req, 20) as res:
                res.read()
            log.info("sales prefix warm")
        except Exception as exc:
            log.warning("sales prefix warm failed %s", type(exc).__name__)

    def _load_fast_stt(self):
        root = os.environ.get(
            "FAST_STT_DIR",
            os.path.expanduser("~/local-ai/models/stt/shenava"),
        )
        py = os.environ.get("FAST_STT_PY", os.path.expanduser("~/local-ai/py"))
        if py and py not in sys.path:
            sys.path.insert(0, py)
        names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
        paths = [os.path.join(root, name) for name in names]
        if not all(os.path.isfile(path) for path in paths):
            log.info("fast stt missing, whisper stays")
            return None
        try:
            import sherpa_onnx
        except Exception:
            log.warning("fast stt import failed", exc_info=True)
            return None
        rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=paths[0],
            decoder=paths[1],
            joiner=paths[2],
            tokens=paths[3],
            num_threads=4,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
        log.info("fast stt ready %s", root)
        return rec

    def _fast_transcribe(self, pcm16_8k: bytes) -> str:
        up = resample_pcm16(pcm16_8k, 8000, 16000)
        samples = array.array("h")
        samples.frombytes(up[: len(up) - (len(up) % 2)])
        if not samples:
            return ""
        floats = array.array("f", (sample / 32768.0 for sample in samples))
        stream = self._fast_stt.create_stream()
        stream.accept_waveform(16000, floats)
        self._fast_stt.decode_stream(stream)
        return str(stream.result.text or "").strip()

    def transcribe(self, pcm16_8k: bytes) -> tuple[str, float]:
        with self._stt_lock:
            return self._transcribe(pcm16_8k)

    def _transcribe(self, pcm16_8k: bytes) -> tuple[str, float]:
        started = time.monotonic()
        if self._fast_stt is not None:
            try:
                text = self._fast_transcribe(pcm16_8k)
                return text, time.monotonic() - started
            except Exception:
                log.warning("fast stt failed", exc_info=True)
        wav = pcm16_to_wav(pcm16_8k, 8000)
        audio_ctx = int(os.environ.get("WHISPER_AC", "512"))
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav)
            path = tmp.name
        try:
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = self.whisper_lib + (
                ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
            )
            proc = subprocess.run(
                [
                    self.whisper_bin,
                    "-m",
                    self.whisper_model,
                    "-f",
                    path,
                    "-l",
                    "fa",
                    "-nt",
                    "-np",
                    "--no-gpu",
                    "-nf",
                    "-t",
                    "8",
                    "-ac",
                    str(audio_ctx),
                    "-mc",
                    "0",
                    "-bs",
                    os.environ.get("WHISPER_BEAM", "1"),
                    "-bo",
                    os.environ.get("WHISPER_BEAM", "1"),
                ],
                capture_output=True,
                env=env,
                timeout=30,
                check=False,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        text = (proc.stdout or b"").decode("utf-8", errors="replace")
        text = JUNK.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
            log.warning("whisper failed rc=%s %s", proc.returncode, err)
            return "", time.monotonic() - started
        return text, time.monotonic() - started

    def reply(self, user_text: str) -> tuple[str, float]:
        started = time.monotonic()
        self.history.append({"role": "user", "content": user_text})
        self.history = self.history[-8:]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history]
        payload = dumps(
            {
                "model": self.llm_model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 48,
                "chat_template_kwargs": {"reasoning_effort": "low"},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.llm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                body = loads(res.read().decode("utf-8"))
        except Exception as exc:
            log.warning("llm failed %s", type(exc).__name__)
            spoken = "الان نرسید. یک لحظهٔ دیگر بگو."
            self.history.append({"role": "assistant", "content": spoken})
            return spoken, time.monotonic() - started
        message = ((body.get("choices") or [{}])[0].get("message") or {})
        raw = str(message.get("content") or "")
        spoken = speakable(raw) or "بگو ببینم منظورت چیه."
        self.history.append({"role": "assistant", "content": spoken})
        return spoken, time.monotonic() - started

    def sales_say(self, brief: str, heard: str, sentences: int = 1) -> tuple[str, float]:
        started = time.monotonic()
        if brief and not self.sales_system:
            self.sales_system = brief
        parts: list[str] = []
        try:
            for bit in self.sales_stream(heard.strip() or "شروع تماس"):
                parts.append(str(bit.get("sentence") or ""))
                if len(parts) >= max(1, sentences):
                    break
        except Exception:
            log.warning("sales llm failed", exc_info=True)
            spoken = "الان نرسید. یک لحظهٔ دیگر بگو."
            self.commit_assistant(spoken)
            return spoken, time.monotonic() - started
        spoken = " ".join(part for part in parts if part).strip() or "بگو، گوش می‌کنم."
        self.commit_assistant(spoken)
        return spoken, time.monotonic() - started

    def _can_fallback(self) -> bool:
        return bool(self.llm_fallback_url) and (
            self.llm_fallback_url != self.llm_url or self.llm_fallback_model != self.llm_model
        )

    def _bench(self) -> bool:
        return os.environ.get("LLM_BENCH", "").strip().lower() in {"1", "true", "yes"}

    def _hops(self) -> list[tuple[str, str]]:
        hops = [(self.llm_url, self.llm_model)]
        if self._bench():
            return hops
        if self._can_fallback():
            hops.append((self.llm_fallback_url, self.llm_fallback_model))
        local = (
            chat_completions_url(os.environ.get("LLM_LOCAL_URL", "http://127.0.0.1:19292/v1")),
            os.environ.get("LLM_LOCAL_MODEL", "qwen3.5-9b"),
        )
        if local not in hops:
            hops.append(local)
        return hops

    def _sales_payload(self, url: str, model: str, messages: list[dict]) -> bytes:
        return dumps(sales_request_body(url, model, messages)).encode("utf-8")

    def _sales_headers(self, url: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if not llm_is_local(url):
            key = os.environ.get("LLM_API_KEY", "").strip()
            if key:
                headers["Authorization"] = "Bearer " + key
        return headers

    def sales_stream(self, cue: str, cancel: threading.Event | None = None):
        started = time.monotonic()
        text = (cue or "").strip() or "شروع تماس"
        self.history.append({"role": "user", "content": text})
        system = self.sales_system or ""
        messages = mask_messages(
            self.llm_url,
            [{"role": "system", "content": system}, *self.history],
        )
        spoke = False
        hops = self._hops()
        for index, (url, model) in enumerate(hops):
            if index:
                log.info("sales llm fallback")
            try:
                for bit in self._sales_events(url, model, messages, cancel, started):
                    if str(bit.get("sentence") or "").strip() or _has_tool_tag(str(bit.get("raw") or "")):
                        spoke = True
                    yield bit
            except Exception as exc:
                log.warning("sales stream failed %s %s", type(exc).__name__, getattr(exc, "code", ""))
            if spoke or (cancel is not None and cancel.is_set()):
                return
        elapsed = time.monotonic() - started
        self.last_sales_stats = {
            "first_token_s": elapsed,
            "prompt_n": 0,
            "predicted_n": 0,
            "elapsed_s": elapsed,
        }
        yield {
            "sentence": "",
            "raw": "",
            "first_token_s": elapsed,
            "prompt_n": 0,
            "predicted_n": 0,
            "elapsed_s": elapsed,
        }

    def _sales_events(self, url: str, model: str, messages: list[dict], cancel, started: float):
        from sales import stream_tail, take_ready_sentences

        timeout = float(os.environ.get("LLM_TIMEOUT_S", "8"))
        req = urllib.request.Request(
            url,
            data=self._sales_payload(url, model, mask_messages(url, messages)),
            headers=self._sales_headers(url),
            method="POST",
        )
        first_token_s = 0.0
        prompt_n = 0
        predicted_n = 0
        usage_cost = 0.0
        buf = ""
        raw = ""
        sent_count = 0

        def take_usage(body: dict) -> None:
            nonlocal prompt_n, predicted_n, usage_cost
            timings = body.get("timings") or {}
            if isinstance(timings, dict):
                prompt_n = int(timings.get("prompt_n") or prompt_n)
                predicted_n = int(timings.get("predicted_n") or predicted_n)
            usage = body.get("usage") or {}
            if not isinstance(usage, dict) or not usage:
                return
            prompt_n = int(usage.get("prompt_tokens") or prompt_n)
            predicted_n = int(usage.get("completion_tokens") or predicted_n)
            if usage.get("cost") is not None:
                usage_cost = float(usage.get("cost") or 0)
            self.last_usage = {"cost": usage_cost, "prompt": prompt_n, "completion": predicted_n}

        def pack(sentence: str) -> dict:
            return {
                "sentence": sentence,
                "raw": raw,
                "first_token_s": first_token_s,
                "prompt_n": prompt_n,
                "predicted_n": predicted_n,
                "elapsed_s": time.monotonic() - started,
                "cost": usage_cost,
                "model": model,
            }

        with open_llm(url, req, timeout) as res:
            leftover = b""
            finished = False
            while not finished:
                if cancel is not None and cancel.is_set():
                    break
                chunk = res.read(256)
                if not chunk:
                    break
                leftover += chunk
                while b"\n" in leftover:
                    line, leftover = leftover.split(b"\n", 1)
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded.startswith("data:"):
                        continue
                    data = decoded[5:].strip()
                    if not data or data == "[DONE]":
                        finished = True
                        break
                    try:
                        body = loads(data)
                    except Exception:
                        continue
                    take_usage(body)
                    delta = ((body.get("choices") or [{}])[0].get("delta") or {})
                    piece = str(delta.get("content") or "")
                    if not piece:
                        continue
                    if not first_token_s and piece.strip():
                        first_token_s = time.monotonic() - started
                    # Keep reading after two sentences: a tool tag ([پایان]، [آدرس]...) usually comes last.
                    raw += piece
                    if sent_count >= 2:
                        continue
                    buf += piece
                    ready, buf = take_ready_sentences(buf)
                    for sentence in ready:
                        sent_count += 1
                        yield pack(sentence)
                        if sent_count >= 2:
                            break
        tail = stream_tail(buf) if sent_count < 2 else ""
        if tail:
            yield pack(tail)
        if "[" in raw:
            # Nothing more to say, but the full text carries the tags the gateway acts on.
            yield pack("")
        self.last_sales_stats = {
            "first_token_s": first_token_s,
            "prompt_n": prompt_n,
            "predicted_n": predicted_n,
            "elapsed_s": time.monotonic() - started,
            "cost": usage_cost,
        }

    def synthesize(self, text: str, *, cloud: bool = True) -> tuple[bytes, float]:
        started = time.monotonic()
        spoken = speakable(text, 3) or text.strip()
        if not spoken:
            return b"", 0.0
        if cloud and tts_model():
            phone = self.cloud_pcm(spoken, tts_first_s())
            if phone:
                return phone, time.monotonic() - started
            log.info("tts fallback piper")
        raw = b""
        try:
            raw = self.piper.synth_raw(spoken)
        except Exception:
            log.warning("piper worker synth failed", exc_info=True)
            raw = self._synth_once(spoken)
        if not raw:
            return b"", time.monotonic() - started
        phone = amplify_pcm16(raw, src_rate=22050)
        return phone, time.monotonic() - started

    def prefetch_cloud(self, text: str) -> bytes:
        spoken = speakable(text, 3) or (text or "").strip()
        if not spoken or not tts_model():
            return b""
        path = self._tts_cache_path(spoken)
        if path.is_file() and path.stat().st_size > 400:
            return path.read_bytes()
        phone = self.cloud_pcm(spoken, 12.0)
        if not phone:
            phone = self.cloud_pcm(spoken, 12.0)
        if not phone:
            return b""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(phone)
        os.chmod(path, 0o600)
        return phone

    def _tts_cache_path(self, text: str) -> Path:
        root = Path(os.environ.get("TTS_CACHE", os.path.expanduser("~/local-ai/sozan-voice-cache")))
        stamp = "\n".join((tts_model(), os.environ.get("TTS_VOICE", "Kore").strip(), TTS_STYLE, text))
        name = hashlib.sha256(stamp.encode("utf-8")).hexdigest()
        return root / f"{name}.pcm"

    def cloud_pcm(self, text: str, first_s: float) -> bytes:
        model = tts_model()
        key = os.environ.get("LLM_API_KEY", "").strip()
        if not model or not key or not text:
            return b""
        voice = os.environ.get("TTS_VOICE", "Kore").strip()
        body = cloud_speech_body(model, voice, mask_private(text))
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/audio/speech",
            data=dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            res = _DIRECT.open(req, timeout=first_s + 8)
        except Exception as exc:
            # HTTPError carries the status (402 = no OpenRouter credit, 400 = bad model id); log it, never the body.
            log.warning("tts cloud failed %s %s", type(exc).__name__, getattr(exc, "code", ""))
            return b""
        try:
            ctype = res.headers.get("content-type") or ""
            if not ctype.startswith("audio/"):
                log.warning("tts cloud not audio")
                return b""
            rate = 24000
            if "rate=" in ctype:
                try:
                    rate = int(ctype.split("rate=")[1].split(";")[0])
                except ValueError:
                    rate = 24000
            chunks: list[bytes] = []
            broken = False
            while True:
                try:
                    part = res.read(4096)
                except Exception as exc:
                    log.warning("tts cloud read %s", type(exc).__name__)
                    broken = True
                    break
                if not part:
                    break
                if not chunks:
                    first = time.monotonic() - started
                    if first > first_s:
                        log.info("tts cloud late %.2f", first)
                        return b""
                chunks.append(part)
            if broken:
                return b""
        finally:
            res.close()
        pcm = b"".join(chunks)
        if len(pcm) < 400:
            return b""
        phone = resample_pcm16(pcm, rate, 8000)
        return match_rms_pcm16(phone)

    def _synth_once(self, spoken: str) -> bytes:
        env = os.environ.copy()
        lib = os.path.dirname(self.piper_bin)
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        proc = subprocess.run(
            [
                self.piper_bin,
                "--model",
                self.piper_model,
                "--output_raw",
                "--espeak_data",
                self.espeak_data,
                *piper_voice_args(),
            ],
            input=spoken.encode("utf-8"),
            capture_output=True,
            env=env,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
            log.warning("piper failed rc=%s %s", proc.returncode, err)
            return b""
        return proc.stdout
