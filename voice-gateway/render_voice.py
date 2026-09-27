"""Render A/B telephone-band samples of Sozan's voice for a listening check."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio_codec import (
    analyze_tx_pcm,
    encode_pcm16,
    decode_to_pcm16,
    pcm16_to_wav,
)
from brain import Brain, amplify_pcm16, amplify_pcm16_python
from sales import ADDRESS_LINE, HELLO_LINE

OUT = Path("/tmp/sozan-ab")
PITCH_LINE = "سوزان برای پیج‌های فروشگاهی اینستاگرام رایگان وبسایت می‌سازه."
PITCH_BANG = "سوزان برای پیج‌های فروشگاهی اینستاگرام رایگان وبسایت می‌سازه!"
HELLO_BANG = HELLO_LINE.replace("می‌سازیم.", "می‌سازیم!")

LINES = {
    "hello": HELLO_LINE,
    "address": ADDRESS_LINE,
    "pitch": PITCH_LINE,
}
BANG_LINES = {
    "hello": HELLO_BANG,
    "address": ADDRESS_LINE,
    "pitch": PITCH_BANG,
}

VARIANTS = (
    {"id": "A", "chain": "python", "length": "0.95", "noise": "0.667", "noise_w": "0.8", "pitch": "1.0", "bang": False},
    {"id": "B", "chain": "ffmpeg", "length": "0.95", "noise": "0.667", "noise_w": "0.8", "pitch": "1.0", "bang": False},
    {"id": "C", "chain": "ffmpeg", "length": "0.88", "noise": "0.8", "noise_w": "1.0", "pitch": "1.0", "bang": False},
    {"id": "D", "chain": "ffmpeg", "length": "0.88", "noise": "0.8", "noise_w": "1.0", "pitch": "1.04", "bang": False},
    {"id": "E", "chain": "ffmpeg", "length": "0.88", "noise": "0.8", "noise_w": "1.0", "pitch": "1.0", "bang": True},
    {"id": "F", "chain": "ffmpeg", "length": "0.88", "noise": "0.8", "noise_w": "1.0", "pitch": "1.04", "bang": True},
)


def through_alaw(pcm: bytes) -> bytes:
    return decode_to_pcm16(encode_pcm16(pcm, "pcma"), "pcma")


def _set_piper(variant: dict[str, str | bool]) -> None:
    os.environ["PIPER_LENGTH"] = str(variant["length"])
    os.environ["PIPER_NOISE"] = str(variant["noise"])
    os.environ["PIPER_NOISE_W"] = str(variant["noise_w"])
    os.environ["VOICE_PITCH"] = str(variant["pitch"])
    os.environ["VOICE_CHAIN"] = str(variant["chain"])


def _phone(raw: bytes, variant: dict[str, str | bool]) -> bytes:
    if variant["id"] == "A":
        return through_alaw(amplify_pcm16_python(raw, gain=1.0, src_rate=22050))
    return through_alaw(amplify_pcm16(raw, gain=1.0, src_rate=22050))


def _report(path: Path, pcm: bytes) -> str:
    stats = analyze_tx_pcm(pcm, 8000)
    return (
        f"{path.name} rms={stats['rms']:.0f} peak={stats['peak']} "
        f"clips={stats['clips']} ms={stats['ms']} gaps={stats['gaps_300ms']}"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    brain = Brain()
    rows: list[str] = []
    for variant in VARIANTS:
        _set_piper(variant)
        pool = BANG_LINES if variant["bang"] else LINES
        joined: list[bytes] = []
        for name, line in pool.items():
            raw = brain._synth_once(line)
            if not raw:
                raise SystemExit(f"piper failed for {variant['id']} {name}")
            phone = _phone(raw, variant)
            path = OUT / f"{variant['id']}-{name}.wav"
            path.write_bytes(pcm16_to_wav(phone, 8000))
            rows.append(_report(path, phone))
            joined.append(phone)
            joined.append(b"\x00" * 1600)
        combo = b"".join(joined)
        path = OUT / f"{variant['id']}-all.wav"
        path.write_bytes(pcm16_to_wav(combo, 8000))
        rows.append(_report(path, combo))
    for row in rows:
        print(row)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
