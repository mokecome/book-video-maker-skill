"""ffmpeg + libx264 render engine — extracted verbatim from generate.py v3.0.

Behavior is byte-identical to the original create_video_with_alignment.
"""

import random
import subprocess
from pathlib import Path

from .common import get_font_path


def is_available() -> tuple[bool, str]:
    from .common import detect_ffmpeg
    return detect_ffmpeg()


def _escape(text: str) -> str:
    return text.replace("'", "").replace(":", "").replace("\\", "")


def render(
    run_dir: Path,
    segments: list,
    bg_paths: list,
    voice_path: Path,
    voice_dir: Path,
    timestamps: list,
    book_title: str,
    book_author: str,
) -> Path | None:
    print("\n[3/3] 生成视频片段 (engine=ffmpeg)...")

    cn_font = get_font_path("msyhbd.ttf")
    en_font = get_font_path("arial.ttf")
    title_font = get_font_path("msyhbd.ttf")
    author_font = get_font_path("msyh.ttf")

    videos = []
    num_segs = len(segments)

    random.seed(42)
    directions = []
    for i in range(num_segs):
        if i == 0:
            directions.append(random.randint(0, 3))
        else:
            d = random.randint(0, 3)
            while d == directions[-1]:
                d = random.randint(0, 3)
            directions.append(d)

    for i, seg in enumerate(segments):
        ts = timestamps[i]
        duration = ts["duration"]

        cn_c = _escape(seg["cn"])
        en_c = _escape(seg.get("en", ""))

        out_file = run_dir / f"seg_{i}.mp4"
        bg = bg_paths[i % len(bg_paths)]

        fade_time = min(0.3, duration * 0.2)

        cn_f = (
            f"drawtext=text='{cn_c}':fontfile={cn_font}:fontsize=52:fontcolor=white"
            f":x=(w-text_w)/2:y=(h*7/10):shadowx=4:shadowy=4:shadowcolor=black@0.7"
            f":enable='if(lt(t,{fade_time}),t/{fade_time},1)'"
        )
        en_f = (
            f"drawtext=text='{en_c}':fontfile={en_font}:fontsize=36:fontcolor=white"
            f":x=(w-text_w)/2:y=(h*7/10)+65:shadowx=3:shadowy=3:shadowcolor=black@0.6"
            f":enable='if(lt(t,{fade_time}),t/{fade_time},1)'"
        )
        title_f = (
            f"drawtext=text='《{book_title}》':fontfile={title_font}:fontsize=84:fontcolor=0x87CEEB"
            f":x=(w-text_w)/2:y=(h*3/10):shadowx=4:shadowy=4:shadowcolor=black@0.7,"
            f"drawtext=text='作者：{book_author}':fontfile={author_font}:fontsize=48:fontcolor=0xFFA500"
            f":x=(w-text_w)/2:y=(h*3/10)+80:shadowx=3:shadowy=3:shadowcolor=black@0.6"
        )

        dir_idx = directions[i]
        if dir_idx == 0:
            vf = f"scale=1188:2112,crop=1080:1920:t*60:100,{title_f},{cn_f},{en_f}"
        elif dir_idx == 1:
            vf = f"scale=1188:2112,crop=1080:1920:108-t*60:100,{title_f},{cn_f},{en_f}"
        elif dir_idx == 2:
            vf = f"scale=1188:2112,crop=1080:1920:50:t*60,{title_f},{cn_f},{en_f}"
        else:
            vf = f"scale=1188:2112,crop=1080:1920:50:192-t*60,{title_f},{cn_f},{en_f}"

        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-i", str(bg),
                "-t", str(duration),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-profile:v", "high", "-level", "4.0",
                "-movflags", "+faststart",
                str(out_file),
            ],
            capture_output=True, text=True,
        )

        if out_file.exists() and out_file.stat().st_size > 1000:
            videos.append(out_file)
        else:
            print(f"    [WARN] 片段{i+1}生成失败: {result.stderr[:100]}")

        print(f"  [{i+1}/{num_segs}] {duration:.2f}s")

    if not videos:
        print("[ERROR] 没有片段")
        return None

    print("\n  合并视频...")
    concat_file = run_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for v in videos:
            f.write(f"file '{str(v.absolute()).replace(chr(92), '/')}'\n")

    merged = run_dir / "merged.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-c", "copy", str(merged)],
        capture_output=True,
    )

    output = run_dir / "final.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(merged), "-i", str(voice_path),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)],
        capture_output=True, text=True,
    )

    if not output.exists():
        print(f"[ERROR] 合并失败: {result.stderr[:200]}")
        return None

    return output
