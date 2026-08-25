import subprocess
from pathlib import Path

from . import project as project_mod

TRANSITIONS = ["fade", "dissolve", "wipeleft", "slideleft", "smoothup"]


class AssembleError(RuntimeError):
    pass


def _timeline(durations: list[float], tail: float, transition: float):
    visible = [d + tail for d in durations]
    starts = []
    offsets = []
    acc = 0.0
    for i, v in enumerate(visible):
        if i > 0:
            acc -= transition
            starts.append(acc)
            offsets.append(acc)
        acc += v
    total = acc
    return visible, starts, offsets, total


def build_command(
    project: project_mod.Project,
    width: int,
    height: int,
    fps: int,
    transition: str,
    transition_dur: float,
    tail_pad: float,
    bgm_path: Path | None,
    bgm_volume: float,
    out_path: Path,
):
    scenes = project.data["scenes"]
    if not scenes:
        raise AssembleError("No plan yet. Generate the shot list first.")

    inputs = []
    missing = []
    for scene in scenes:
        idx = scene["index"]
        if not project.has_clip(idx):
            missing.append(idx)
    if missing:
        raise AssembleError(
            "Missing clips for scene(s): "
            + ", ".join(str(i) for i in missing)
            + f". Put downloaded clips in {project.clips_dir} as scene_01.mp4 etc."
        )

    durations = []
    for scene in scenes:
        idx = scene["index"]
        audio_path = project.audio_path(idx)
        if not audio_path.exists():
            raise AssembleError(f"Narration audio missing for scene {idx}. Re-run planning.")
        try:
            durations.append(project_mod.media_duration(audio_path))
        except Exception as exc:
            raise AssembleError(f"Could not measure audio for scene {idx}: {exc}") from exc

    if transition_dur <= 0:
        transition_dur = 0.0
    if tail_pad <= transition_dur + 0.05:
        tail_pad = transition_dur + 0.35

    n = len(scenes)
    visible, starts, offsets, total = _timeline(durations, tail_pad, transition_dur)

    for scene in scenes:
        idx = scene["index"]
        clip = project.clip_path(idx)
        inputs += ["-i", str(clip)]
    for scene in scenes:
        idx = scene["index"]
        inputs += ["-i", str(project.audio_path(idx))]
    if bgm_path:
        inputs += ["-stream_loop", "-1", "-i", str(bgm_path)]

    filters = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale=w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration={visible[i]:.3f},"
            f"trim=duration={visible[i]:.3f},setpts=PTS-STARTPTS,setsar=1[v{i}]"
        )
    if n == 1:
        last_video_label = "[v0]"
    else:
        prev = "v0"
        for k in range(n - 1):
            label = f"x{k}" if k < n - 2 else "vout"
            filters.append(
                f"[{prev}][v{k + 1}]xfade=transition={transition}"
                f":duration={transition_dur:.3f}:offset={offsets[k]:.3f}[{label}]"
            )
            prev = label
        last_video_label = "[vout]"

    for i in range(n):
        if n == 1:
            slot = total
        elif i == 0:
            slot = starts[0]
        elif i == n - 1:
            slot = total - starts[i - 1]
        else:
            slot = starts[i] - starts[i - 1]
        filters.append(
            f"[{n + i}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad=whole_dur={slot:.3f}[a{i}]"
        )

    cat_labels = "".join(f"[a{i}]" for i in range(n))
    filters.append(f"{cat_labels}concat=n={n}:v=0:a=1[cat]")
    filters.append(
        "[cat]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[voice]"
    )

    final_audio = "voice"
    if bgm_path:
        fade_start = max(0.0, total - 2.0)
        filters.append(
            f"[{2 * n}:a]atrim=duration={total:.3f},volume={bgm_volume:.2f},"
            f"afade=t=in:d=1,afade=t=out:st={fade_start:.3f}:d=2[bgm]"
        )
        filters.append("[voice][bgm]amix=inputs=2:duration=first:normalize=0[mix]")
        final_audio = "mix"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        last_video_label,
        "-map",
        f"[{final_audio}]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(out_path),
    ]
    return cmd, total


def _parse_progress(line: str) -> float | None:
    if line.startswith("out_time="):
        value = line.split("=", 1)[1].strip()
        try:
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except ValueError:
            return None
    return None


def assemble(
    project: project_mod.Project,
    cfg: dict,
    aspect: str,
    transition: str = "fade",
    transition_dur: float = 0.5,
    tail_pad: float = 0.85,
    bgm_file: str | None = None,
    bgm_volume: float = 0.15,
    progress_cb=None,
) -> tuple[Path, float]:
    from . import config

    width, height = config.ASPECT_RESOLUTIONS.get(aspect, (1920, 1080))
    out_path = project.dir / "final.mp4"
    cmd, total = build_command(
        project,
        width,
        height,
        cfg.get("fps", 30),
        transition,
        transition_dur,
        tail_pad,
        Path(bgm_file) if bgm_file else None,
        bgm_volume,
        out_path,
    )
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    for line in process.stdout:
        seconds = _parse_progress(line.strip())
        if seconds is not None and progress_cb and total > 0:
            progress_cb(min(1.0, seconds / total))
    process.wait()
    stderr = process.stderr.read() if process.stderr else ""
    if process.returncode != 0:
        raise AssembleError(
            f"FFmpeg failed (exit {process.returncode}):\n{stderr[-2000:]}"
        )
    return out_path, total
