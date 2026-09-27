"""G.711 and tiny PCM helpers for 8 kHz phone audio. No third-party deps."""

from __future__ import annotations

import array
import math
import struct
import wave
from io import BytesIO

_SEG_END = (0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF)


def _alaw_encode_sample(sample: int) -> int:
    # Asterisk/spandsp scale: segment ends are full 16-bit, then AMI mask.
    if sample >= 0:
        mask = 0xD5
        pcm = sample if sample < 32767 else 32767
    else:
        mask = 0x55
        pcm = -sample if sample > -32768 else 32767
    seg = 7
    for i, end in enumerate(_SEG_END):
        if pcm <= end:
            seg = i
            break
    shift = 4 if seg == 0 else seg + 3
    aval = (seg << 4) | ((pcm >> shift) & 0x0F)
    return aval ^ mask


def _alaw_decode_sample(value: int) -> int:
    value ^= 0x55
    quant = (value & 0x0F) << 4
    seg = (value & 0x70) >> 4
    if seg:
        linear = (quant + 0x108) << (seg - 1)
    else:
        linear = quant + 8
    return linear if (value & 0x80) else -linear


def _ulaw_encode_sample(sample: int) -> int:
    BIAS = 0x84
    CLIP = 32635
    if sample < 0:
        sample = -sample
        sign = 0x80
    else:
        sign = 0
    if sample > CLIP:
        sample = CLIP
    sample += BIAS
    exp = 7
    mask = 0x4000
    while exp > 0 and (sample & mask) == 0:
        mask >>= 1
        exp -= 1
    mantissa = (sample >> (exp + 3)) & 0x0F
    return (~(sign | (exp << 4) | mantissa)) & 0xFF


def _ulaw_decode_sample(value: int) -> int:
    value = (~value) & 0xFF
    sign = value & 0x80
    exp = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa << 3) + 0x84) << exp
    sample -= 0x84
    return -sample if sign else sample


def encode_pcm16(pcm: bytes, kind: str) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if kind == "pcma":
        fn = _alaw_encode_sample
    elif kind == "pcmu":
        fn = _ulaw_encode_sample
    else:
        raise ValueError(kind)
    return bytes(fn(s) for s in samples)


def decode_to_pcm16(payload: bytes, kind: str) -> bytes:
    if kind == "pcma":
        fn = _alaw_decode_sample
    elif kind == "pcmu":
        fn = _ulaw_decode_sample
    else:
        raise ValueError(kind)
    out = array.array("h", (fn(b) for b in payload))
    return out.tobytes()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    src = array.array("h")
    src.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not src or src_rate == dst_rate:
        return src.tobytes()
    n_out = max(1, int(len(src) * dst_rate / src_rate))
    out = array.array("h", [0] * n_out)
    if n_out == 1:
        out[0] = src[0]
        return out.tobytes()
    scale = (len(src) - 1) / (n_out - 1)
    last = len(src) - 1
    for i in range(n_out):
        x = i * scale
        j = int(x)
        frac = x - j
        a = src[j]
        b = src[j + 1] if j < last else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


class PcmJitter:
    """Reorder RTP and hide a missing packet so speech is not squeezed together."""

    def __init__(self, depth: int = 4) -> None:
        self.depth = depth
        self.buf: dict[int, bytes] = {}
        self.nxt: int | None = None
        self.last = b""
        self.gaps = 0

    def push(self, seq: int, pcm: bytes) -> list[bytes]:
        seq &= 0xFFFF
        if self.nxt is not None:
            behind = (self.nxt - seq) & 0xFFFF
            if 0 < behind < 32768:
                return []
            ahead = (seq - self.nxt) & 0xFFFF
            if 50 < ahead < 32768:
                self.buf.clear()
                self.nxt = None
        self.buf[seq] = pcm
        if self.nxt is None:
            if len(self.buf) < self.depth:
                return []
            self.nxt = min(self.buf)
        if not self.last:
            self.last = pcm
        out: list[bytes] = []
        while self.nxt is not None:
            if self.nxt in self.buf:
                frame = self.buf.pop(self.nxt)
                self.last = frame
                out.append(frame)
                self.nxt = (self.nxt + 1) & 0xFFFF
                continue
            if len(self.buf) < self.depth:
                break
            out.append(self.last)
            self.gaps += 1
            self.nxt = (self.nxt + 1) & 0xFFFF
        return out


def highpass_pcm16(pcm: bytes, rate: int = 8000, cutoff: float = 80.0) -> bytes:
    """Drop rumble below the telephone band."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples or rate <= 0:
        return pcm
    coeff = math.exp(-2.0 * math.pi * cutoff / rate)
    prev_x = 0
    prev_y = 0.0
    out = array.array("h")
    for sample in samples:
        filtered = sample - prev_x + coeff * prev_y
        prev_x = sample
        prev_y = filtered
        clipped = int(filtered)
        if clipped > 32767:
            clipped = 32767
        elif clipped < -32768:
            clipped = -32768
        out.append(clipped)
    return out.tobytes()


def presence_pcm16(pcm: bytes, rate: int, low: float = 1200.0, high: float = 3200.0, db: float = 5.0) -> bytes:
    """Lift the speech-clarity band without raising rumble or harsh treble."""
    if not pcm or db == 0:
        return pcm
    band = lowpass_pcm16(highpass_pcm16(pcm, rate, low), rate, high)
    gain = 10.0 ** (db / 20.0) - 1.0
    src = array.array("h")
    extra = array.array("h")
    src.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    extra.frombytes(band[: len(band) - (len(band) % 2)])
    n = min(len(src), len(extra))
    out = array.array("h")
    for i in range(n):
        value = int(src[i] + gain * extra[i])
        if value > 32767:
            value = 32767
        elif value < -32768:
            value = -32768
        out.append(value)
    return out.tobytes()


def match_rms_pcm16(pcm: bytes, target: float = 7300.0, ceiling: float = 30000.0) -> bytes:
    """Make each sentence about the same loudness, then soft-limit peaks."""
    level = rms(pcm)
    if level < 80 or target <= 0:
        return pcm
    gain = target / level
    return limit_pcm16(pcm, gain, ceiling)


def limit_pcm16(pcm: bytes, gain: float = 1.7, ceiling: float = 30000.0) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return pcm
    knee = 16000.0
    room = max(1.0, ceiling - knee)
    out = array.array("h")
    for sample in samples:
        lifted = sample * gain
        mag = abs(lifted)
        if mag <= knee:
            shaped = mag
        else:
            shaped = knee + room * (1.0 - math.exp(-(mag - knee) / room))
        if shaped > ceiling:
            shaped = ceiling
        value = int(shaped if lifted >= 0 else -shaped)
        out.append(value)
    return out.tobytes()


def lowpass_pcm16(pcm: bytes, rate: int, cutoff: float = 3400.0) -> bytes:
    """Cut treble before dropping the sample rate onto a telephone line."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples or rate <= 0:
        return pcm
    alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / rate)
    prev = 0.0
    out = array.array("h")
    for sample in samples:
        prev = prev + alpha * (sample - prev)
        clipped = int(prev)
        if clipped > 32767:
            clipped = 32767
        elif clipped < -32768:
            clipped = -32768
        out.append(clipped)
    return out.tobytes()


def gate_kind(pcm: bytes) -> str:
    """Classify 8 kHz phone audio before speech recognition.

    A steady tone or hold-music bed must not be sent to Whisper.
    Real syllables have quiet gaps or a swinging level.
    """
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    frame = 160
    if len(samples) < frame * 8:
        return "short"
    loud: list[float] = []
    quiet = 0
    total = 0
    for start in range(0, len(samples) - frame + 1, frame):
        chunk = samples[start : start + frame]
        total += 1
        energy = 0
        for sample in chunk:
            energy += sample * sample
        level = (energy / frame) ** 0.5
        if level < 180:
            quiet += 1
            continue
        loud.append(level)
    if total == 0 or len(loud) < 4:
        return "noise"
    mean = sum(loud) / len(loud)
    variance = sum((level - mean) ** 2 for level in loud) / len(loud)
    swing = (variance ** 0.5) / mean if mean else 0.0
    quiet_ratio = quiet / total
    if quiet_ratio >= 0.10 or swing >= 0.22:
        return "speech"
    if swing < 0.15 and quiet_ratio < 0.08:
        return "tone"
    if quiet_ratio < 0.05:
        return "music"
    return "noise"


def rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def pcm_stats(pcm: bytes, rate: int = 8000) -> dict[str, float | int]:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return {"rms": 0.0, "peak": 0, "clips": 0, "ms": 0, "n": 0}
    peak = 0
    clips = 0
    acc = 0
    for sample in samples:
        mag = abs(sample)
        if mag > peak:
            peak = mag
        if mag >= 32767:
            clips += 1
        acc += sample * sample
    return {
        "rms": (acc / len(samples)) ** 0.5,
        "peak": peak,
        "clips": clips,
        "ms": int(len(samples) * 1000 / max(1, rate)),
        "n": len(samples),
    }


def analyze_tx_pcm(pcm: bytes, rate: int = 8000) -> dict[str, float | int | list[int]]:
    """Loudness, peak, clipping, and quiet gaps over 300 ms in the middle of a reply."""
    stats = pcm_stats(pcm, rate)
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    frame = max(1, int(rate * 0.02))
    levels: list[float] = []
    for start in range(0, len(samples) - frame + 1, frame):
        chunk = samples[start : start + frame]
        energy = 0
        for sample in chunk:
            energy += sample * sample
        levels.append((energy / frame) ** 0.5)
    start = 0
    end = len(levels)
    while start < end and levels[start] < 80:
        start += 1
    while end > start and levels[end - 1] < 80:
        end -= 1
    gaps: list[int] = []
    run = 0
    for level in levels[start:end]:
        if level < 80:
            run += 1
        else:
            if run * 20 >= 300:
                gaps.append(run * 20)
            run = 0
    if run * 20 >= 300:
        gaps.append(run * 20)
    stats["gaps_300ms"] = len(gaps)
    stats["gap_ms_total"] = sum(gaps)
    return stats


def pcm_similarity(left: bytes, right: bytes) -> float:
    """Scale-invariant cosine of two 16-bit PCM frames. Echo of our own TX is high."""
    n = min(len(left), len(right))
    n -= n % 2
    if n < 64:
        return 0.0
    a = array.array("h")
    b = array.array("h")
    a.frombytes(left[:n])
    b.frombytes(right[:n])
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for x_val, y_val in zip(a, b):
        dot += x_val * y_val
        left_norm += x_val * x_val
        right_norm += y_val * y_val
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm) ** 0.5


def pcm16_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def chunk_pcm(pcm: bytes, frame_bytes: int = 320) -> list[bytes]:
    pcm = pcm[: len(pcm) - (len(pcm) % 2)]
    if len(pcm) < frame_bytes:
        pcm = pcm + b"\x00" * (frame_bytes - len(pcm))
    return [pcm[i : i + frame_bytes] for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes)]


def rtp_packet(seq: int, ts: int, ssrc: int, payload: bytes, *, marker: bool = False, pt: int = 8) -> bytes:
    second = (0x80 if marker else 0) | (pt & 0x7F)
    return struct.pack("!BBHII", 0x80, second, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc & 0xFFFFFFFF) + payload


def rtp_parse(packet: bytes) -> tuple[int, int, bytes] | None:
    if len(packet) < 12:
        return None
    b0, b1, seq, ts, _ssrc = struct.unpack("!BBHII", packet[:12])
    if (b0 >> 6) != 2:
        return None
    cc = b0 & 0x0F
    offset = 12 + 4 * cc
    if b0 & 0x10:
        if len(packet) < offset + 4:
            return None
        ext_len = struct.unpack("!H", packet[offset + 2 : offset + 4])[0]
        offset += 4 + ext_len * 4
    if offset > len(packet):
        return None
    payload = packet[offset:]
    if b0 & 0x20 and payload:
        pad = payload[-1]
        if pad < len(payload):
            payload = payload[:-pad]
    return b1 & 0x7F, seq, payload
