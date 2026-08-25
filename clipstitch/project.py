import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()).strip("_")
    return name[:40] or "project"


class Project:
    def __init__(self, directory: Path):
        self.dir = directory
        self.json_path = directory / "project.json"
        self.audio_dir = directory / "audio"
        self.clips_dir = directory / "clips"
        self.data = {
            "name": directory.name,
            "created": None,
            "script": "",
            "style": "",
            "voice": "",
            "aspect": "16:9 (landscape)",
            "scenes": [],
        }

    @classmethod
    def create(cls, name: str) -> "Project":
        directory = config.PROJECTS_DIR / safe_name(name)
        n = 2
        while directory.exists():
            directory = config.PROJECTS_DIR / f"{safe_name(name)}_{n}"
            n += 1
        p = cls(directory)
        p.data["created"] = datetime.now(timezone.utc).isoformat()
        p.ensure_dirs()
        p.save()
        return p

    @classmethod
    def open(cls, name: str) -> "Project":
        directory = config.PROJECTS_DIR / safe_name(name)
        if not directory.exists():
            raise FileNotFoundError(f"Project '{name}' does not exist.")
        p = cls(directory)
        if p.json_path.exists():
            stored = json.loads(p.json_path.read_text(encoding="utf-8"))
            p.data.update(stored)
        p.data["name"] = directory.name
        p.ensure_dirs()
        return p

    def ensure_dirs(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ensure_dirs()
        self.json_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def audio_path(self, index: int) -> Path:
        return self.audio_dir / f"scene_{index:02d}.mp3"

    def clip_path(self, index: int, ext: str = "") -> Path:
        matches = sorted(self.clips_dir.glob(f"scene_{index:02d}.*"))
        for m in matches:
            if m.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
                return m
        if ext:
            return self.clips_dir / f"scene_{index:02d}{ext}"
        return self.clips_dir / f"scene_{index:02d}.mp4"

    def has_clip(self, index: int) -> bool:
        path = self.clip_path(index)
        return path.exists() and path.suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".mkv",
            ".avi",
        }

    def clip_status(self) -> list[dict]:
        rows = []
        for scene in self.data["scenes"]:
            idx = scene["index"]
            has_audio = self.audio_path(idx).exists()
            has_clip = self.has_clip(idx)
            dur = ""
            if has_clip:
                try:
                    dur = f"{media_duration(self.clip_path(idx)):.1f}s"
                except Exception:
                    dur = "?"
            rows.append(
                {
                    "#": idx,
                    "narration": (scene.get("narration") or "")[:60],
                    "audio": "yes" if has_audio else "MISSING",
                    "clip": dur if has_clip else "missing",
                }
            )
        return rows

    def missing_clips(self) -> list[int]:
        return [s["index"] for s in self.data["scenes"] if not self.has_clip(s["index"])]

    def write_shot_list(self) -> Path:
        lines = [f"# Shot list - {self.data['name']}", ""]
        for s in self.data["scenes"]:
            lines.append(f"## Scene {s['index']}  ({s.get('duration') or '?'}s narration)")
            lines.append("")
            lines.append(f"**Narration:** {s['narration']}")
            lines.append("")
            lines.append(f"**Video prompt:** {s['prompt']}")
            lines.append("")
            lines.append(f"Save the downloaded clip as: `clips/scene_{s['index']:02d}.mp4`")
            lines.append("")
        out = self.dir / "shot_list.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    @staticmethod
    def list_projects() -> list[str]:
        if not config.PROJECTS_DIR.exists():
            return []
        return sorted(
            d.name for d in config.PROJECTS_DIR.iterdir() if (d / "project.json").exists()
        )
