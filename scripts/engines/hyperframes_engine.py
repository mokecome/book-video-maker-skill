"""Hyperframes render engine (experimental).

Generates a Hyperframes project inside run_dir/hyperframes/ and invokes
`npx hyperframes render`. Tested target: hyperframes >= 0.6.x.

[experimental] The HTML schema is built from public docs (README + quickstart
+ llms.txt) but text/animation conventions are not 100% nailed down; expect
small tweaks on first real run.
"""

import json
import shutil
import subprocess
from html import escape
from pathlib import Path


def is_available() -> tuple[bool, str]:
    from .common import detect_hyperframes
    return detect_hyperframes()


# Ken Burns variants (CSS transforms). 4 directions, alternated by segment.
_KB_CSS = """
@keyframes kb-left-right { from {transform: scale(1.1) translateX(-3%);} to {transform: scale(1.1) translateX(3%);} }
@keyframes kb-right-left { from {transform: scale(1.1) translateX(3%);}  to {transform: scale(1.1) translateX(-3%);} }
@keyframes kb-top-bottom { from {transform: scale(1.1) translateY(-3%);} to {transform: scale(1.1) translateY(3%);} }
@keyframes kb-bottom-top { from {transform: scale(1.1) translateY(3%);}  to {transform: scale(1.1) translateY(-3%);} }
"""

_KB_NAMES = ["kb-left-right", "kb-right-left", "kb-top-bottom", "kb-bottom-top"]


def _copy_assets(run_dir: Path, project_dir: Path, bg_paths: list, voice_dir: Path, num_segs: int) -> Path:
    """Copy bg images, per-segment voice mp3s, and fonts into project assets/."""
    assets = project_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    # Background images: rename to bg_00.jpg ... bg_NN.{ext}
    for i, bg in enumerate(bg_paths):
        target = assets / f"bg_{i:02d}{bg.suffix.lower()}"
        if target.resolve() != bg.resolve():
            shutil.copy2(bg, target)

    # Per-segment voice mp3s (produced by generate_voice_with_timestamps)
    for i in range(num_segs):
        src = voice_dir / f"seg_{i:02d}.mp3"
        if src.exists():
            shutil.copy2(src, assets / f"seg_{i:02d}.mp3")

    # Fonts
    fonts_root = Path(__file__).parent.parent.parent / "fonts"
    for f in ["msyhbd.ttf", "msyh.ttf", "arial.ttf",
              "NotoSansCJKsc-Bold.ttf", "NotoSansCJKsc-Regular.ttf"]:
        src = fonts_root / f
        if src.exists():
            shutil.copy2(src, assets / f)

    return assets


def _find_asset_image_ext(assets: Path, idx: int) -> str:
    for ext in ("jpg", "jpeg", "png", "webp"):
        if (assets / f"bg_{idx:02d}.{ext}").exists():
            return ext
    return "jpg"


def _build_html(segments: list, timestamps: list, assets: Path,
                book_title: str, book_author: str,
                width: int, height: int) -> str:
    total = timestamps[-1]["end"] if timestamps else 0.0

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    parts.append("<style>")
    # Font registration (msyh primary, NotoSans fallback for Linux/commercial)
    parts.append("""
@font-face { font-family: 'CN-Bold';    src: url('assets/msyhbd.ttf') format('truetype'),
                                              url('assets/NotoSansCJKsc-Bold.ttf') format('truetype'); }
@font-face { font-family: 'CN-Regular'; src: url('assets/msyh.ttf') format('truetype'),
                                              url('assets/NotoSansCJKsc-Regular.ttf') format('truetype'); }
@font-face { font-family: 'EN';         src: url('assets/arial.ttf') format('truetype'); }
""")
    parts.append(f"""
html, body {{ margin:0; padding:0; background:#000; width:{width}px; height:{height}px; overflow:hidden; }}
#stage {{ position:relative; width:{width}px; height:{height}px; background:#000; overflow:hidden; }}
.bg {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover;
       animation-timing-function: linear; animation-fill-mode: both; }}
.scrim {{ position:absolute; inset:0; background:linear-gradient(to bottom, rgba(0,0,0,0.35), rgba(0,0,0,0.55) 70%, rgba(0,0,0,0.7)); }}
.title-block {{ position:absolute; top:30%; left:0; right:0; text-align:center; }}
.title-block .book   {{ font-family:'CN-Bold'; font-size:84px; color:#87CEEB; text-shadow: 4px 4px 0 rgba(0,0,0,0.7); margin:0; }}
.title-block .author {{ font-family:'CN-Regular'; font-size:48px; color:#FFA500; text-shadow: 3px 3px 0 rgba(0,0,0,0.6); margin-top:20px; }}
.caption {{ position:absolute; top:70%; left:0; right:0; text-align:center;
            animation: fade-in 0.3s linear both; }}
.caption .cn {{ font-family:'CN-Bold'; font-size:52px; color:#fff; text-shadow: 4px 4px 0 rgba(0,0,0,0.7); margin:0; }}
.caption .en {{ font-family:'EN'; font-size:36px; color:#fff; text-shadow: 3px 3px 0 rgba(0,0,0,0.6); margin-top:15px; }}
@keyframes fade-in {{ from {{opacity:0}} to {{opacity:1}} }}
""")
    parts.append(_KB_CSS)
    parts.append("</style></head><body>")

    parts.append(
        f'<div id="stage" data-composition-id="book-video" '
        f'data-start="0" data-duration="{total:.3f}" '
        f'data-width="{width}" data-height="{height}">'
    )

    # Persistent book/author overlay (track 3)
    parts.append(
        f'<div class="clip title-block" data-start="0" data-duration="{total:.3f}" data-track-index="3">'
        f'<div class="book">《{escape(book_title)}》</div>'
        f'<div class="author">作者：{escape(book_author)}</div>'
        f'</div>'
    )

    for i, seg in enumerate(segments):
        ts = timestamps[i]
        start = ts["start"]
        dur = ts["duration"]
        kb = _KB_NAMES[i % 4]
        # alternate so adjacent segments use different directions
        if i > 0 and _KB_NAMES[(i - 1) % 4] == kb:
            kb = _KB_NAMES[(i + 1) % 4]
        ext = _find_asset_image_ext(assets, i)

        # Image clip (track 0) — Ken Burns via CSS keyframes
        parts.append(
            f'<img class="clip bg" data-start="{start:.3f}" data-duration="{dur:.3f}" '
            f'data-track-index="0" src="assets/bg_{i:02d}.{ext}" '
            f'style="animation-name:{kb}; animation-duration:{dur:.3f}s;">'
        )

        # Scrim for caption legibility (track 1)
        parts.append(
            f'<div class="clip scrim" data-start="{start:.3f}" data-duration="{dur:.3f}" '
            f'data-track-index="1"></div>'
        )

        # Caption (track 2)
        cn = escape(seg.get("cn", ""))
        en = escape(seg.get("en", ""))
        parts.append(
            f'<div class="clip caption" data-start="{start:.3f}" data-duration="{dur:.3f}" '
            f'data-track-index="2">'
            f'<div class="cn">{cn}</div>'
            + (f'<div class="en">{en}</div>' if en else "")
            + '</div>'
        )

        # Audio (track 4)
        parts.append(
            f'<audio class="clip" data-start="{start:.3f}" data-duration="{dur:.3f}" '
            f'data-track-index="4" data-volume="1.0" '
            f'src="assets/seg_{i:02d}.mp3"></audio>'
        )

    parts.append("</div></body></html>")
    return "\n".join(parts)


def _write_meta(project_dir: Path, width: int, height: int, fps: int, duration: float):
    meta = {
        "name": "book-video",
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(duration, 3),
    }
    (project_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
    print("\n[3/3] 生成视频 (engine=hyperframes, experimental)...")

    width, height, fps = 1080, 1920, 30
    project_dir = run_dir / "hyperframes"
    project_dir.mkdir(parents=True, exist_ok=True)

    assets = _copy_assets(run_dir, project_dir, bg_paths, voice_dir, len(segments))
    html = _build_html(segments, timestamps, assets, book_title, book_author, width, height)
    (project_dir / "index.html").write_text(html, encoding="utf-8")
    _write_meta(project_dir, width, height, fps, timestamps[-1]["end"] if timestamps else 0.0)

    output = run_dir / "final.mp4"
    print(f"  project: {project_dir}")
    print(f"  invoking: npx hyperframes render --output {output}")

    result = subprocess.run(
        ["npx", "--yes", "hyperframes", "render", "--output", str(output.absolute())],
        cwd=str(project_dir),
        capture_output=True, text=True,
    )

    if result.returncode != 0 or not output.exists():
        print("[ERROR] hyperframes render failed")
        print("stdout:", result.stdout[-800:])
        print("stderr:", result.stderr[-800:])
        return None

    return output
