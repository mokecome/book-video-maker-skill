#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书单爆款短视频生成器 v3.0
OpenClaw Skill 模式 - agent 預生圖 + 本地語音/影片合成

職責劃分:
- 图像生成: 由 OpenClaw agent 透過內建 image_generate (Codex OAuth) 預生並放入 run_dir
- 语音合成: edge-tts (本地)
- 視訊合成: ffmpeg + libx264 (本地)

依赖:
- Python >= 3.8
- FFmpeg (建議含 libx264)
- 預生圖片必須在執行前放好（檔名 bg_00.jpg ~ bg_NN.jpg，或 png/webp）
"""

import asyncio
import json
import subprocess
import random
import argparse
import sys
import platform
from pathlib import Path
from datetime import datetime

# ============= 自动安装依赖 =============
def install_dependencies():
    """自动安装Python依赖"""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("正在安装依赖包...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "edge-tts", "-q"])
        print("依赖安装完成")

install_dependencies()

import edge_tts

# ============= 配置 =============
OUTPUT_DIR = Path("output")
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
RECOMMENDED_IMAGE_SIZE = "1024x1536"  # agent 生圖時推薦傳給 image_generate 的 size
DEFAULT_VOICE = "zh-CN-YunxiNeural"

# 跨平台字体路径
def get_font_path(font_name: str) -> str:
    """获取跨平台字体路径"""
    system = platform.system()
    script_dir = Path(__file__).parent.parent
    
    # 优先使用技能包内置字体
    local_font = script_dir / "fonts" / font_name
    if local_font.exists():
        return str(local_font)
    
    # 系统字体路径
    if system == "Windows":
        return f"/Windows/Fonts/{font_name}"
    elif system == "Darwin":  # macOS
        return f"/System/Library/Fonts/{font_name}"
    else:  # Linux
        # 尝试常见路径
        linux_paths = [
            f"/usr/share/fonts/truetype/{font_name}",
            f"/usr/share/fonts/{font_name}",
            f"/usr/local/share/fonts/{font_name}",
            str(Path.home() / ".fonts" / font_name),
        ]
        for p in linux_paths:
            if Path(p).exists():
                return p
        # 回退到默认
        return font_name


# ============= 圖片收集（agent 預生圖模式） =============
def find_image(directory: Path, index: int):
    """在指定目錄找 bg_NN.{jpg|jpeg|png|webp}，回傳第一個找到的 Path 或 None"""
    for ext in IMAGE_EXTENSIONS:
        p = directory / f"bg_{index:02d}.{ext}"
        if p.exists() and p.stat().st_size > 1000:
            return p
    return None


def print_image_manifest(segments: list, target_dir: Path):
    """輸出 agent 該如何用 image_generate 補齊缺圖的指令清單"""
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
    print("OpenClaw agent: 對每一條呼叫內建 image_generate (走 Codex OAuth)，")
    print("                依上述檔名儲存到目標目錄，然後重新執行本腳本。")
    print("CLI 獨立使用: 請手動準備好上述圖片再執行。")
    print("="*70 + "\n")


def collect_images(run_dir: Path, segments: list, images_dir):
    """收集預生成的背景圖。優先順序:
    1. --images-dir 指定的目錄
    2. run_dir 內 (agent 預設輸出位置)
    缺圖時印出詳細 manifest 並 exit。
    """
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
    rate: str = "+0%"
) -> tuple:
    """逐句生成语音并记录精准时间戳"""
    print(f"\n[2/3] 生成语音（逐句对齐）...")
    
    voice_dir = run_dir / "voices"
    voice_dir.mkdir(exist_ok=True)
    
    timestamps = []
    all_voice_files = []
    current_time = 0.0
    
    for i, seg in enumerate(segments):
        voice_file = voice_dir / f"seg_{i:02d}.mp3"
        
        # 生成单句语音
        communicate = edge_tts.Communicate(seg["cn"], voice, rate=rate)
        
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        
        with open(voice_file, "wb") as f:
            for c in chunks:
                f.write(c)
        
        # 获取语音时长
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(voice_file)],
            capture_output=True, text=True
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        
        # 记录时间戳
        timestamps.append({
            "start": current_time,
            "end": current_time + duration,
            "duration": duration,
            "text": seg["cn"],
            "index": i
        })
        
        all_voice_files.append(voice_file)
        current_time += duration
        
        print(f"  [{i+1}/{len(segments)}] {duration:.2f}s | {seg['cn'][:20]}...")
    
    # 合并语音文件
    print(f"\n  合并语音...")
    merged_voice = run_dir / "voice_merged.mp3"
    
    concat_file = run_dir / "voice_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for vf in all_voice_files:
            f.write(f"file '{str(vf.absolute()).replace(chr(92), '/')}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(merged_voice)
    ], capture_output=True)
    
    total_dur = timestamps[-1]["end"] if timestamps else 0
    print(f"  总时长: {total_dur:.2f}s ({len(timestamps)}句)")
    
    return merged_voice, timestamps


# ============= 视频生成 =============
def escape_text(text: str) -> str:
    """转义ffmpeg特殊字符"""
    return text.replace("'", "").replace(":", "").replace("\\", "")


def create_video_with_alignment(
    run_dir: Path, 
    bg_paths: list, 
    voice_path: Path, 
    timestamps: list,
    segments: list,
    book_title: str,
    book_author: str
):
    """根据精准时间戳生成视频片段"""
    print(f"\n[3/3] 生成视频片段...")
    
    # 获取字体路径
    cn_font = get_font_path("msyhbd.ttf")
    en_font = get_font_path("arial.ttf")
    title_font = get_font_path("msyhbd.ttf")
    author_font = get_font_path("msyh.ttf")
    
    videos = []
    num_segs = len(segments)
    
    # Ken Burns方向（相邻不同）
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
        
        cn_c = escape_text(seg["cn"])
        en_c = escape_text(seg.get("en", ""))
        
        out_file = run_dir / f"seg_{i}.mp4"
        bg = bg_paths[i % len(bg_paths)]
        
        # 渐显时长
        fade_time = min(0.3, duration * 0.2)
        
        # 中文字幕 + 渐显
        cn_f = (
            f"drawtext=text='{cn_c}':fontfile={cn_font}:fontsize=52:fontcolor=white"
            f":x=(w-text_w)/2:y=(h*7/10):shadowx=4:shadowy=4:shadowcolor=black@0.7"
            f":enable='if(lt(t,{fade_time}),t/{fade_time},1)'"
        )
        
        # 英文字幕 + 渐显
        en_f = (
            f"drawtext=text='{en_c}':fontfile={en_font}:fontsize=36:fontcolor=white"
            f":x=(w-text_w)/2:y=(h*7/10)+65:shadowx=3:shadowy=3:shadowcolor=black@0.6"
            f":enable='if(lt(t,{fade_time}),t/{fade_time},1)'"
        )
        
        # 书名作者（无渐显，一直显示）
        title_f = (
            f"drawtext=text='《{book_title}》':fontfile={title_font}:fontsize=84:fontcolor=0x87CEEB"
            f":x=(w-text_w)/2:y=(h*3/10):shadowx=4:shadowy=4:shadowcolor=black@0.7,"
            f"drawtext=text='作者：{book_author}':fontfile={author_font}:fontsize=48:fontcolor=0xFFA500"
            f":x=(w-text_w)/2:y=(h*3/10)+80:shadowx=3:shadowy=3:shadowcolor=black@0.6"
        )
        
        # Ken Burns方向
        dir_idx = directions[i]
        
        if dir_idx == 0:    # 左→右
            vf = f"scale=1188:2112,crop=1080:1920:t*60:100,{title_f},{cn_f},{en_f}"
        elif dir_idx == 1:  # 右→左
            vf = f"scale=1188:2112,crop=1080:1920:108-t*60:100,{title_f},{cn_f},{en_f}"
        elif dir_idx == 2:  # 上→下
            vf = f"scale=1188:2112,crop=1080:1920:50:t*60,{title_f},{cn_f},{en_f}"
        else:               # 下→上
            vf = f"scale=1188:2112,crop=1080:1920:50:192-t*60,{title_f},{cn_f},{en_f}"
        
        # 使用精准时长
        result = subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(bg),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-profile:v", "high", "-level", "4.0",
            "-movflags", "+faststart",
            str(out_file)
        ], capture_output=True, text=True)
        
        if out_file.exists() and out_file.stat().st_size > 1000:
            videos.append(out_file)
        else:
            print(f"    [WARN] 片段{i+1}生成失败: {result.stderr[:100]}")
        
        print(f"  [{i+1}/{num_segs}] {duration:.2f}s")
    
    if len(videos) == 0:
        print("[ERROR] 没有片段")
        return None
    
    # 合并视频
    print(f"\n  合并视频...")
    concat_file = run_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for v in videos:
            f.write(f"file '{str(v.absolute()).replace(chr(92), '/')}'\n")
    
    merged = run_dir / "merged.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(merged)
    ], capture_output=True)
    
    # 添加音频
    output = run_dir / "final.mp4"
    result = subprocess.run([
        "ffmpeg", "-y", "-i", str(merged), "-i", str(voice_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)
    ], capture_output=True, text=True)
    
    if not output.exists():
        print(f"[ERROR] 合并失败: {result.stderr[:200]}")
    
    return output


# ============= 主函数 =============
async def main():
    parser = argparse.ArgumentParser(description="书单爆款短视频生成器 v3.0 - OpenClaw Skill 模式")
    parser.add_argument("--book", "-b", required=True, help="书名")
    parser.add_argument("--author", "-a", required=True, help="作者")
    parser.add_argument("--quotes", "-q", help="金句JSON文件路径")
    parser.add_argument("--output", "-o", default="output", help="输出目录")
    parser.add_argument("--voice", "-v", default=DEFAULT_VOICE, help="语音声音")
    parser.add_argument("--rate", "-r", default="+0%", help="语速")
    parser.add_argument("--images-dir", "-I", help="預生圖目錄 (預設為 run_dir 自身)")
    parser.add_argument("--run-dir", help="重用既有的 run_dir (避免每次新建時間戳目錄)")
    args = parser.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = Path(args.output)

    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = OUTPUT_DIR / f"{args.book}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print(f"《{args.book}》爆款视频生成 v3.0")
    print(f"run_dir: {run_dir}")
    print("=" * 50)
    
    # 加载金句
    if args.quotes:
        with open(args.quotes, "r", encoding="utf-8") as f:
            segments = json.load(f)
        print(f"加载金句: {args.quotes} ({len(segments)}句)")
    else:
        # 使用内置模板
        template_path = Path(__file__).parent.parent / "templates" / "rich_dad_poor_dad.json"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                segments = json.load(f)
            print(f"使用默认模板: rich_dad_poor_dad.json ({len(segments)}句)")
        else:
            print("[ERROR] 未指定金句文件且默认模板不存在")
            print("请使用 -q 参数指定金句JSON文件")
            return
    
    # 更新第一句书名
    if segments:
        segments[0]["cn"] = f"今天分享的是：《{args.book}》。"
    
    # 收集預生圖 (由 OpenClaw agent 或使用者預先放好)
    bg_paths = collect_images(run_dir, segments, args.images_dir)
    
    # 生成语音
    voice_path, timestamps = await generate_voice_with_timestamps(
        run_dir, segments, args.voice, args.rate
    )
    
    # 生成视频
    output = create_video_with_alignment(
        run_dir, bg_paths, voice_path, timestamps, 
        segments, args.book, args.author
    )
    
    if output and output.exists():
        size = output.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"[SUCCESS] 视频生成完成!")
        print(f"大小: {size:.1f}MB")
        print(f"路径: {output}")
        print(f"{'='*50}")
    else:
        print("\n[FAILED] 视频生成失败")


if __name__ == "__main__":
    asyncio.run(main())
