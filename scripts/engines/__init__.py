"""Render engines for book-video-maker.

Each engine exposes:
    is_available() -> tuple[bool, str]   # (ok, reason)
    render(run_dir, segments, bg_paths, voice_path, voice_dir, timestamps,
           book, author) -> Path | None
"""
