#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书单爆款短视频生成器 v3.1
OpenClaw Skill 模式 - agent 預生圖 + 本地語音 + 可插拔引擎合成

職責劃分:
- 图像生成: agent 透過內建 image_generate (Codex OAuth) 預生並放入 run_dir
- 语音合成: edge-tts (本地)
- 視訊合成: 兩條路徑
    * hyperframes (HTML/CSS/JS + Puppeteer + FFmpeg) — 預設優先
    * ffmpeg + libx264                                — 自動 fallback

依赖:
- Python >= 3.8
- FFmpeg (ffmpeg engine 與音訊處理皆需要)
- Node.js >= 22 + hyperframes (可選；hyperframes 引擎用)
- 預生圖片必須在執行前放好（檔名 bg_00.jpg ~ bg_NN.jpg，或 png/webp）
"""

import asyncio
import json
import subprocess
import argparse
import sys
from pathlib import Path
from datetime import datetime

# ============= 自动安装依赖 =============
def install_dependencies():
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("正在安装依赖包...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "edge-tts", "-q"])
        print("依赖安装完成")

install_dependencies()

import edge_tts

# 加入 scripts/ 到 sys.path 讓 engines 子套件可被 import
sys.path.insert(0, str(Path(__file__).parent))
from engines import common, ffmpeg_engine, hyperframes_engine  # noqa: E402

# ============= 配置 =============
OUTPUT_DIR = Path("output")
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
RECOMMENDED_IMAGE_SIZE = "1024x1536"
DEFAULT_VOICE = "zh-TW-YunJheNeural"

ENGINES = {
    "ffmpeg": ffmpeg_engine,
    "hyperframes": hyperframes_engine,
}


# ============= 圖片收集（agent 預生圖模式） =============
def find_image(directory: Path, index: int):
    for ext in IMAGE_EXTENSIONS:
        p = directory / f"bg_{index:02d}.{ext}"
        if p.exists() and p.stat().st_size > 1000:
            return p
    return None


def print_image_manifest(segments: list, target_dir: Path):
    print("\n" + "="*70)
    print("[ACTION REQUIRED] 需要預先生成下列背景圖再執行本腳本：")
    print(f"目標目錄: {target_dir}")
    print("="*70)
    print(f"\n建議 image_generate 參數: size=\"{RECOMMENDED_IMAGE_SIZE}\", count=1, outputFormat=\"jpeg\"")
    print(f"檔名規則: bg_<兩位數編號>.jpg (例: bg_00.jpg, bg_01.jpg, ...)\n")
    for i, seg in enumerate(segments):
        prompt = seg.get("prompt", "book illustration, cinematic")
        print(f"  bg_{i:02d}.jpg")
        print(f"    prompt: {prompt}")
    print("\n" + "="*70)
    print("agent: 對每一條呼叫內建 image_generate (走 Codex OAuth)，")
    print("       依上述檔名儲存到目標目錄，然後重新執行本腳本。")
    print("CLI 獨立使用: 請手動準備好上述圖片再執行。")
    print("="*70 + "\n")


def collect_images(run_dir: Path, segments: list, images_dir):
    source_dir = Path(images_dir) if images_dir else run_dir
    print(f"\n[1/3] 載入背景圖 (來源: {source_dir})...")

    paths = []
    missing = []
    for i in range(len(segments)):
        p = find_image(source_dir, i)
        if p is None:
            missing.append(i)
        else:
            paths.append(p)
            print(f"  [{i+1}/{len(segments)}] {p.name}")

    if missing:
        print(f"\n[ERROR] 缺少 {len(missing)} 張圖: {missing}")
        print_image_manifest(segments, source_dir)
        sys.exit(2)

    return paths


# ============= 语音生成（精准对齐） =============
async def generate_voice_with_timestamps(
    run_dir: Path,
    segments: list,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> tuple:
    print(f"\n[2/3] 生成语音（逐句对齐）...")

    voice_dir = run_dir / "voices"
    voice_dir.mkdir(exist_ok=True)

    timestamps = []
    all_voice_files = []
    current_time = 0.0

    for i, seg in enumerate(segments):
        voice_file = voice_dir / f"seg_{i:02d}.mp3"

        communicate = edge_tts.Communicate(seg["cn"], voice, rate=rate)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        with open(voice_file, "wb") as f:
            for c in chunks:
                f.write(c)

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(voice_file)],
            capture_output=True, text=True,
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])

        timestamps.append({
            "start": current_time,
            "end": current_time + duration,
            "duration": duration,
            "text": seg["cn"],
            "index": i,
        })

        all_voice_files.append(voice_file)
        current_time += duration

        print(f"  [{i+1}/{len(segments)}] {duration:.2f}s | {seg['cn'][:20]}...")

    print(f"\n  合并语音...")
    merged_voice = run_dir / "voice_merged.mp3"

    concat_file = run_dir / "voice_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for vf in all_voice_files:
            f.write(f"file '{str(vf.absolute()).replace(chr(92), '/')}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(merged_voice),
    ], capture_output=True)

    total_dur = timestamps[-1]["end"] if timestamps else 0
    print(f"  总时长: {total_dur:.2f}s ({len(timestamps)}句)")

    return merged_voice, voice_dir, timestamps


# ============= 主函数 =============
async def main():
    parser = argparse.ArgumentParser(description="书单爆款短视频生成器 v3.1")
    parser.add_argument("--book", "-b", required=True, help="书名")
    parser.add_argument("--author", "-a", required=True, help="作者")
    parser.add_argument("--quotes", "-q", help="金句JSON文件路径")
    parser.add_argument("--output", "-o", default="output", help="输出目录")
    parser.add_argument("--voice", "-v", default=DEFAULT_VOICE, help="语音声音")
    parser.add_argument("--rate", "-r", default="+0%", help="语速")
    parser.add_argument("--images-dir", "-I", help="預生圖目錄 (預設為 run_dir 自身)")
    parser.add_argument("--run-dir", help="重用既有的 run_dir")
    parser.add_argument(
        "--engine", "-e",
        choices=["auto", "ffmpeg", "hyperframes"],
        default="auto",
        help="合成引擎: auto=偵測（優先 hyperframes，缺 Node 退 ffmpeg）",
    )
    args = parser.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = Path(args.output)

    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = OUTPUT_DIR / f"{args.book}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir.mkdir(parents=True, exist_ok=True)

    # 選擇引擎（失敗時 raise 並中止，使用者看得到原因）
    try:
        engine_name, engine_reason = common.pick_engine(args.engine)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        sys.exit(3)

    print("=" * 50)
    print(f"《{args.book}》爆款视频生成 v3.1")
    print(f"run_dir: {run_dir}")
    print(f"engine:  {engine_name}  ({engine_reason})")
    print("=" * 50)

    # 加载金句
    if args.quotes:
        with open(args.quotes, "r", encoding="utf-8") as f:
            segments = json.load(f)
        print(f"加载金句: {args.quotes} ({len(segments)}句)")
    else:
        template_path = Path(__file__).parent.parent / "templates" / "rich_dad_poor_dad.json"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                segments = json.load(f)
            print(f"使用默认模板: rich_dad_poor_dad.json ({len(segments)}句)")
        else:
            print("[ERROR] 未指定金句文件且默认模板不存在")
            print("请使用 -q 参数指定金句JSON文件")
            return

    if segments:
        segments[0]["cn"] = f"今天分享的是：《{args.book}》。"

    bg_paths = collect_images(run_dir, segments, args.images_dir)

    voice_path, voice_dir, timestamps = await generate_voice_with_timestamps(
        run_dir, segments, args.voice, args.rate
    )

    engine = ENGINES[engine_name]
    output = engine.render(
        run_dir, segments, bg_paths, voice_path, voice_dir,
        timestamps, args.book, args.author,
    )

    if output and output.exists():
        size = output.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"[SUCCESS] 视频生成完成! (engine={engine_name})")
        print(f"大小: {size:.1f}MB")
        print(f"路径: {output}")
        print(f"{'='*50}")
    else:
        print(f"\n[FAILED] 视频生成失败 (engine={engine_name})")
        sys.exit(4)


if __name__ == "__main__":
    asyncio.run(main())
