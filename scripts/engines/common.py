"""Shared helpers: engine detection and font lookup."""

import platform
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> tuple[int, str]:
    # Resolve first arg via PATH so Windows .cmd shims (npx, npm) work without shell=True.
    resolved = shutil.which(cmd[0]) or cmd[0]
    try:
        r = subprocess.run([resolved, *cmd[1:]],
                           capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def detect_ffmpeg() -> tuple[bool, str]:
    if shutil.which("ffmpeg") is None:
        return False, "ffmpeg not on PATH"
    rc, out = _run(["ffmpeg", "-hide_banner", "-encoders"])
    if rc != 0:
        return False, f"ffmpeg -encoders failed: {out[:120]}"
    if "libx264" not in out:
        return False, "ffmpeg present but libx264 encoder missing (GPL build required)"
    return True, "ok"


def detect_hyperframes() -> tuple[bool, str]:
    """Passive detection — never installs. Treat 'installed globally' (binary on
    PATH) or 'available in local node_modules/.bin' as available."""
    if shutil.which("node") is None:
        return False, "node not on PATH"
    rc, out = _run(["node", "--version"])
    if rc != 0:
        return False, f"node --version failed: {out[:120]}"
    ver = out.lstrip("v").split(".")[0]
    if not ver.isdigit() or int(ver) < 22:
        return False, f"node >= 22 required, found {out}"

    # 1) global install: `hyperframes` binary on PATH
    hf = shutil.which("hyperframes")
    if hf:
        rc, out = _run([hf, "--version"])
        if rc == 0:
            return True, f"hyperframes {out.splitlines()[0]} (global)"

    # 2) local install: ./node_modules/.bin/hyperframes
    local = Path.cwd() / "node_modules" / ".bin" / (
        "hyperframes.cmd" if platform.system() == "Windows" else "hyperframes"
    )
    if local.exists():
        rc, out = _run([str(local), "--version"])
        if rc == 0:
            return True, f"hyperframes {out.splitlines()[0]} (local)"

    return False, "hyperframes not installed (install: npm i -g hyperframes)"


def pick_engine(preference: str) -> tuple[str, str]:
    """Return (engine_name, reason). preference ∈ {auto, ffmpeg, hyperframes}."""
    if preference == "ffmpeg":
        ok, why = detect_ffmpeg()
        if not ok:
            raise RuntimeError(f"--engine ffmpeg requested but unavailable: {why}")
        return "ffmpeg", why
    if preference == "hyperframes":
        ok, why = detect_hyperframes()
        if not ok:
            raise RuntimeError(f"--engine hyperframes requested but unavailable: {why}")
        return "hyperframes", why
    hf_ok, hf_why = detect_hyperframes()
    if hf_ok:
        return "hyperframes", hf_why
    ff_ok, ff_why = detect_ffmpeg()
    if ff_ok:
        return "ffmpeg", f"hyperframes unavailable ({hf_why}); using ffmpeg"
    raise RuntimeError(
        f"No usable engine. hyperframes: {hf_why}; ffmpeg: {ff_why}"
    )


def get_font_path(font_name: str) -> str:
    system = platform.system()
    script_dir = Path(__file__).parent.parent.parent
    local_font = script_dir / "fonts" / font_name
    if local_font.exists():
        return str(local_font)
    if system == "Windows":
        return f"/Windows/Fonts/{font_name}"
    if system == "Darwin":
        return f"/System/Library/Fonts/{font_name}"
    for p in [
        f"/usr/share/fonts/truetype/{font_name}",
        f"/usr/share/fonts/{font_name}",
        f"/usr/local/share/fonts/{font_name}",
        str(Path.home() / ".fonts" / font_name),
    ]:
        if Path(p).exists():
            return p
    return font_name
