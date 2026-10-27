"""Mux the real viewer recording, Windows narration and English captions locally."""

import argparse
import json
from pathlib import Path
import subprocess
import textwrap
import wave


def timestamp(seconds: float) -> str:
    total = round(seconds * 1000)
    return f"{total // 3600000:02}:{total // 60000 % 60:02}:{total // 1000 % 60:02},{total % 1000:03}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--directory", type=Path, default=Path(".venv/handoff/owner-d/delivery"))
    args = parser.parse_args()
    folder = args.directory.resolve()
    chapters = json.loads((folder / "chapters.json").read_text(encoding="utf-8"))
    captions = []
    caption_number = 1

    def encode(*command: str) -> None:
        subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *command], cwd=folder, check=True)

    for index, (start, end, narration) in enumerate(chapters):
        audio = folder / f"voice-{index}.wav"
        with wave.open(str(audio)) as recording:
            spoken_s = recording.getnframes() / recording.getframerate()
        if spoken_s > end - start:
            raise ValueError(f"Narration chapter {index} exceeds its slot: {spoken_s:.2f}s")
        encode("-i", str(audio), "-af", "apad", "-t", str(end - start), "-ar", "48000", "-ac", "1", f"chapter-{index}.wav")
        chunks = textwrap.wrap(narration, width=88)
        for part, chunk in enumerate(chunks):
            lo = start + spoken_s * part / len(chunks)
            hi = start + spoken_s * (part + 1) / len(chunks)
            captions.append(f"{caption_number}\n{timestamp(lo)} --> {timestamp(hi)}\n{chunk}\n")
            caption_number += 1
    (folder / "everyfan.srt").write_text("\n".join(captions), encoding="utf-8")
    (folder / "audio-list.txt").write_text("\n".join(f"file 'chapter-{i}.wav'" for i in range(len(chapters))), encoding="utf-8")
    encode("-f", "concat", "-safe", "0", "-i", "audio-list.txt", "-c", "copy", "everyfan-narration.wav")
    encode("-i", "everyfan-raw.webm", "-i", "everyfan-narration.wav", "-t", "115", "-vf",
           "subtitles=everyfan.srt:force_style='FontName=Arial,FontSize=9,BorderStyle=3,Outline=1,MarginV=12'",
           "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "everyfan-demo.mp4")
    for second in (8, 50, 76, 95, 107):
        encode("-ss", str(second), "-i", "everyfan-demo.mp4", "-frames:v", "1", f"review-{second}.png")
    print(folder / "everyfan-demo.mp4")


if __name__ == "__main__":
    main()
