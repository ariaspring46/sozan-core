"""Report loudness, peak, clipping and mid-reply gaps in a TX wav."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

from audio_codec import analyze_tx_pcm


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 analyze_tx.py <file.wav>")
    path = Path(sys.argv[1])
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    stats = analyze_tx_pcm(pcm, rate)
    print(
        f"{path} rms={stats['rms']:.0f} peak={stats['peak']} "
        f"clips={stats['clips']} ms={stats['ms']} "
        f"gaps={stats['gaps_300ms']} gap_ms={stats['gap_ms_total']}"
    )


if __name__ == "__main__":
    main()
