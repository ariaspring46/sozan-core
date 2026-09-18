from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

SIZES = {
    "reel": (1080, 1920),
    "wide": (1920, 1080),
}


class VideoComposeService:
    def __init__(self, ffmpeg: str = "ffmpeg") -> None:
        self.ffmpeg = ffmpeg

    def _run(self, args: list[str]) -> None:
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-4000:] or proc.stdout[-4000:] or "ffmpeg failed")

    def _clip(self, src: Path, dest: Path, size: tuple[int, int], seconds: float, fps: int = 25) -> None:
        w, h = size
        frames = int(seconds * fps)
        vf = (
            f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
            f"crop={w * 2}:{h * 2},"
            f"zoompan=z='min(zoom+0.0009,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={w}x{h}:fps={fps},format=yuv420p"
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                str(src),
                "-t",
                str(seconds),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(dest),
            ]
        )

    def compose(
        self,
        frames: list[Path],
        dest: Path,
        *,
        format_name: str = "reel",
        audio: Path | None = None,
        seconds_per: float = 4.2,
        fade: float = 0.4,
    ) -> Path:
        if not frames:
            raise ValueError("فریم برای ویدیو نیست")
        size = SIZES[format_name]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            clips: list[Path] = []
            for i, frame in enumerate(frames):
                clip = tmp_path / f"clip{i:02d}.mp4"
                self._clip(frame, clip, size, seconds_per)
                clips.append(clip)

            silent = tmp_path / "silent.mp4"
            if len(clips) == 1:
                shutil.copy(clips[0], silent)
            else:
                inputs: list[str] = []
                for c in clips:
                    inputs.extend(["-i", str(c)])
                n = len(clips)
                filters = []
                last = "0:v"
                acc = seconds_per
                for i in range(1, n):
                    offset = acc - fade
                    out = f"v{i}"
                    filters.append(f"[{last}][{i}:v]xfade=transition=fade:duration={fade}:offset={offset}[{out}]")
                    last = out
                    acc += seconds_per - fade
                self._run(
                    [self.ffmpeg, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", f"[{last}]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(silent)]
                )

            if audio and audio.exists():
                self._run(
                    [
                        self.ffmpeg,
                        "-y",
                        "-i",
                        str(silent),
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(audio),
                        "-shortest",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        str(dest),
                    ]
                )
            else:
                shutil.copy(silent, dest)
        return dest
