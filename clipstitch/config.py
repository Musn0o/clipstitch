import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
PROJECTS_DIR = ROOT / "projects"

DEFAULTS = {
    "provider": "auto",
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "openrouter_model": "openrouter/free",
    "voice": "en-US-AvaNeural",
}

ASPECT_RESOLUTIONS = {
    "16:9 (landscape)": (1920, 1080),
    "9:16 (vertical)": (1080, 1920),
    "1:1 (square)": (1080, 1080),
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if os.environ.get("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.environ["GEMINI_API_KEY"]
    if os.environ.get("OPENROUTER_API_KEY"):
        cfg["openrouter_api_key"] = os.environ["OPENROUTER_API_KEY"]
    return cfg


def save(cfg: dict) -> None:
    data = {k: cfg.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def check_system() -> str:
    import shutil

    lines = []
    lines.append(("ffmpeg", "OK" if shutil.which("ffmpeg") else "MISSING"))
    lines.append(("ffprobe", "OK" if shutil.which("ffprobe") else "MISSING"))
    out = []
    for name, status in lines:
        icon = "+" if status == "OK" else "X"
        out.append(f"[{icon}] {name}: {status}")
    if any(s == "MISSING" for _, s in lines):
        out.append("Install FFmpeg, then restart this app. On Windows run in a terminal:")
        out.append("    winget install Gyan.FFmpeg")
    return "\n".join(out)
