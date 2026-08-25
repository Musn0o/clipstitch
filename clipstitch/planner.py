import re
import shutil
import subprocess
from pathlib import Path

from . import llm, project as project_mod, tts


def plan(project: project_mod.Project, cfg: dict, target_seconds: float) -> str:
    script = (project.data.get("script") or "").strip()
    if not script:
        raise RuntimeError("The script is empty.")
    provider = cfg.get("provider", "auto")
    if provider == "manual":
        scenes = llm.manual_split(script, target_seconds)
    else:
        scenes = llm.split_scenes(script, cfg, target_seconds)

    voice = cfg.get("voice") or "en-US-AvaNeural"
    project.data["voice"] = voice
    old_scenes = {s["index"]: s for s in project.data["scenes"]}
    total = 0.0
    for scene in scenes:
        idx = scene["index"]
        audio_path = project.audio_path(idx)
        tts.synthesize(scene["narration"], voice, audio_path)
        duration = project_mod.media_duration(audio_path)
        scene["duration"] = round(duration, 3)
        scene["audio"] = audio_path.name
        if idx in old_scenes and old_scenes[idx].get("prompt"):
            scene["prompt"] = old_scenes[idx]["prompt"] or scene["prompt"]
        total += duration
    project.data["scenes"] = scenes
    project.save()
    project.write_shot_list()
    return (
        f"Planned {len(scenes)} scenes, {total:.1f}s of narration. "
        f"Shot list saved to {project.dir / 'shot_list.md'}."
    )


def regenerate_scene_audio(project: project_mod.Project, index: int) -> str:
    scene = next((s for s in project.data["scenes"] if s["index"] == index), None)
    if scene is None:
        raise RuntimeError(f"No scene #{index} in this project.")
    voice = project.data.get("voice") or "en-US-AvaNeural"
    audio_path = project.audio_path(index)
    tts.synthesize(scene["narration"], voice, audio_path)
    scene["duration"] = round(project_mod.media_duration(audio_path), 3)
    project.save()
    return f"Scene {index} audio regenerated ({scene['duration']:.1f}s)."


def preview_voiceover(project: project_mod.Project) -> Path | None:
    segments = []
    for scene in project.data["scenes"]:
        path = project.audio_path(scene["index"])
        if path.exists():
            segments.append(path)
    if not segments:
        return None
    out = project.dir / "voiceover_preview.mp3"
    list_file = project.dir / "_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in segments), encoding="utf-8"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out),
        ],
        capture_output=True,
        check=True,
    )
    list_file.unlink(missing_ok=True)
    return out


def import_uploaded_clips(project: project_mod.Project, files: list[str]) -> str:
    if not files:
        return "No files uploaded."
    imported, skipped = [], []
    missing = project.missing_clips()
    ordered_missing = iter(missing)
    for file_str in sorted(files):
        src = Path(file_str)
        ext = src.suffix.lower()
        if ext not in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
            skipped.append(src.name)
            continue
        match = re.match(r"scene_(\d+)$", src.stem.lower())
        if match:
            index = int(match.group(1))
        else:
            index = next(ordered_missing, None)
        if index is None:
            skipped.append(src.name)
            continue
        dest = project.clip_path(index, ext)
        shutil.copy2(src, dest)
        imported.append(f"scene_{index:02d}{ext}")
    msg = f"Imported: {', '.join(imported)}." if imported else "Nothing imported."
    if skipped:
        msg += f" Skipped: {', '.join(skipped)}."
    return msg
