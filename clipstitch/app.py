import functools
import traceback

import gradio as gr

from . import assembler, config, planner, project as project_mod, tts

PLAN_HEADERS = ["#", "Narration", "Seconds", "Video prompt"]
CLIP_HEADERS = ["#", "Narration start", "Audio", "Clip found"]


def _error(exc: Exception) -> str:
    if isinstance(exc, (FileNotFoundError, RuntimeError, ValueError)):
        return f"**Error:** {exc}"
    traceback.print_exc()
    return f"**Unexpected error:** {exc}"


class Ui:
    def __init__(self):
        self.cfg = config.load()
        self.voices = tts.list_voices()

    @staticmethod
    def _plan_rows(proj):
        return [
            [s["index"], s["narration"], f"{(s.get('duration') or 0):.1f}", s.get("prompt", "")]
            for s in proj.data["scenes"]
        ]

    @staticmethod
    def _clip_rows(proj):
        return [[r["#"], r["narration"], r["audio"], r["clip"]] for r in proj.clip_status()]

    def _project_rows(self):
        return project_mod.Project.list_projects()

    def build(self):
        with gr.Blocks(title="ClipStitch") as demo:
            s = gr.State(None)
            self._state = s
            gr.Markdown(
                "# ClipStitch\n"
                "Turn a script plus short AI-generated clips into a finished video with "
                "voiceover and crossfades.\n\n**Workflow: 1. Plan -> 2. Shoot -> 3. Assemble**"
            )
            with gr.Accordion("System check", open=False):
                gr.Markdown(f"```\n{config.check_system()}\n```")

            with gr.Row():
                self.project_dd = gr.Dropdown(choices=self._project_rows(),
                                              label="Existing projects", scale=2)
                self.new_name = gr.Textbox(label="New project name", scale=2)
                self.open_btn = gr.Button("Open / Create", variant="primary", scale=1)
            self.project_status = gr.Markdown("No project loaded.")

            self.script_tb = gr.Textbox(label="Script", lines=8,
                                        placeholder="Paste the full narration here...")
            self.style_tb = gr.Textbox(label="Visual style hint (optional)",
                                       placeholder="e.g. cinematic, warm golden light")
            self.voice_dd = gr.Dropdown(choices=self.voices, value=self.cfg.get("voice"),
                                        label="Narrator voice")

            with gr.Tabs():
                with gr.Tab("1. Plan"):
                    self._plan_tab()
                with gr.Tab("2. Shoot"):
                    self._clips_tab()
                with gr.Tab("3. Assemble"):
                    self._assemble_tab()

            self._wire_events()
        return demo

    def _open_handler(self, typed_name, dropdown_value):
        chosen = (typed_name or "").strip() or (dropdown_value or "")
        if not chosen:
            raise ValueError("Type a new project name or pick an existing one.")
        try:
            proj = project_mod.Project.open(chosen)
            verb = "opened"
        except FileNotFoundError:
            proj = project_mod.Project.create(chosen)
            proj.data["voice"] = self.cfg.get("voice", "")
            proj.save()
            verb = "created"
        preview = planner.preview_voiceover(proj)
        shot_md = proj.dir / "shot_list.md"
        status = (
            f"Project **{proj.data['name']}** ({verb}) - folder `{proj.dir}`\n\n"
            f"{len(proj.data['scenes'])} planned scenes."
        )
        return (
            proj,
            status,
            proj.data.get("script", ""),
            proj.data.get("style", ""),
            proj.data.get("voice") or self.cfg.get("voice"),
            proj.data.get("aspect") or "16:9 (landscape)",
            self._plan_rows(proj),
            str(preview) if preview else None,
            str(shot_md) if shot_md.exists() else None,
            str(proj.clips_dir),
            self._clip_rows(proj),
            gr.update(choices=self._project_rows(), value=proj.data["name"]),
        )

    def _safe(self, fn, n_outputs):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                return [_error(exc)] + [None] * (n_outputs - 1)
        return wrapper

    def _plan_tab(self):
        gr.Markdown(
            "ClipStitch splits your script into scenes, generates the narration audio per "
            "scene, and writes a shot list of prompts to paste into your AI video generator."
        )
        self.target_slider = gr.Slider(3, 10, value=5, step=0.5,
                                       label="Target seconds per scene (match clip length)")
        self.aspect_radio = gr.Radio(list(config.ASPECT_RESOLUTIONS.keys()),
                                     value="16:9 (landscape)", label="Aspect ratio")
        with gr.Accordion("AI provider settings", open=False):
            self.provider_radio = gr.Radio(
                ["auto", "gemini", "openrouter", "manual"],
                value=self.cfg.get("provider"),
                label="Scene-splitting provider",
                info="'manual' needs no API key: splits on blank lines or sentences.",
            )
            self.gemini_key = gr.Textbox(label="Gemini API key (free at aistudio.google.com)",
                                         value=self.cfg.get("gemini_api_key"), type="password")
            self.gemini_model = gr.Textbox(label="Gemini model",
                                           value=self.cfg.get("gemini_model"))
            self.openrouter_key = gr.Textbox(label="OpenRouter API key",
                                             value=self.cfg.get("openrouter_api_key"),
                                             type="password")
            self.openrouter_model = gr.Textbox(label="OpenRouter model",
                                               value=self.cfg.get("openrouter_model"))
            self.save_cfg_btn = gr.Button("Save API settings")

        self.plan_btn = gr.Button("Generate shot list + voiceover", variant="primary")
        self.plan_status = gr.Markdown()
        gr.Markdown("### Shot list")
        self.plan_df = gr.Dataframe(headers=PLAN_HEADERS, interactive=False, wrap=True)
        with gr.Row():
            self.preview_audio = gr.Audio(label="Full voiceover preview", interactive=False)
            self.shot_file = gr.File(label="shot_list.md")

        gr.Markdown("### Fix a single scene")
        with gr.Row():
            self.scene_num = gr.Number(label="Scene #", precision=0, minimum=1)
            self.regen_btn = gr.Button("Regenerate this scene's audio")

    def _clips_tab(self):
        gr.Markdown(
            "For every scene: copy its prompt from the Plan tab into your AI video tool "
            "(Kling, Google Flow, Hailuo...), download the clip, then drag it here or drop it "
            "into the `clips` folder using the exact file name shown."
        )
        self.clips_dir_md = gr.Markdown()
        self.clip_df = gr.Dataframe(headers=CLIP_HEADERS, interactive=False, wrap=True)
        self.refresh_btn = gr.Button("Refresh checklist")
        self.upload = gr.File(label="Upload clips (name them scene_01.mp4, scene_02.mp4 ...)",
                              file_count="multiple", file_types=["video"])
        self.upload_status = gr.Markdown()

    def _assemble_tab(self):
        gr.Markdown(
            "Trims each clip to match its narration, adds crossfades and mixes the voiceover "
            "into one finished MP4."
        )
        with gr.Row():
            self.transition_dd = gr.Dropdown(choices=assembler.TRANSITIONS, value="fade",
                                             label="Transition")
            self.trans_slider = gr.Slider(0.2, 1.2, value=0.5, step=0.1,
                                          label="Transition seconds")
            self.tail_slider = gr.Slider(0.3, 2.5, value=0.9, step=0.05,
                                         label="Extra hold after narration (s)")
        self.bgm_file = gr.File(label="Background music (optional, loops and fades out)",
                                file_types=["audio"])
        self.bgm_vol = gr.Slider(0.0, 0.6, value=0.15, step=0.01, label="Music volume")
        self.build_btn = gr.Button("Build final video", variant="primary")
        self.build_status = gr.Markdown()
        self.output_video = gr.Video(label="Final video")

    def _wire_events(self):
        s = self._state
        self.open_btn.click(
            self._safe(self._open_handler, 12),
            inputs=[self.new_name, self.project_dd],
            outputs=[s, self.project_status, self.script_tb, self.style_tb, self.voice_dd,
                     self.aspect_radio, self.plan_df, self.preview_audio, self.shot_file,
                     self.clips_dir_md, self.clip_df, self.project_dd],
        )

        self.save_cfg_btn.click(
            self._save_cfg,
            inputs=[self.provider_radio, self.gemini_key, self.gemini_model,
                    self.openrouter_key, self.openrouter_model],
            outputs=[self.plan_status],
        )

        self.plan_btn.click(
            self._safe(self._do_plan, 6),
            inputs=[s, self.script_tb, self.style_tb, self.voice_dd, self.aspect_radio,
                    self.target_slider, self.provider_radio, self.gemini_key,
                    self.gemini_model, self.openrouter_key, self.openrouter_model],
            outputs=[self.plan_status, self.plan_df, self.preview_audio, self.shot_file,
                     self.clips_dir_md, self.clip_df],
        )

        self.regen_btn.click(
            self._safe(self._do_regen, 3),
            inputs=[s, self.scene_num],
            outputs=[self.plan_status, self.plan_df, self.preview_audio],
        )

        self.refresh_btn.click(
            self._safe(self._do_refresh, 2),
            inputs=[s],
            outputs=[self.clips_dir_md, self.clip_df],
        )

        self.upload.upload(
            self._safe(self._do_upload, 3),
            inputs=[s, self.upload],
            outputs=[self.upload_status, self.clips_dir_md, self.clip_df],
        )

        self.build_btn.click(
            self._safe(self._do_build, 2),
            inputs=[s, self.transition_dd, self.trans_slider, self.tail_slider,
                    self.bgm_file, self.bgm_vol],
            outputs=[self.build_status, self.output_video],
        )

    def _save_cfg(self, provider, gkey, gmodel, okey, omodel):
        self.cfg.update({
            "provider": provider,
            "gemini_api_key": gkey,
            "gemini_model": gmodel,
            "openrouter_api_key": okey,
            "openrouter_model": omodel,
        })
        config.save(self.cfg)
        return "Settings saved to config.json."

    def _do_plan(self, proj, script, style, voice, aspect, target, provider,
                 gkey, gmodel, okey, omodel, progress=gr.Progress()):
        if proj is None:
            raise RuntimeError("Open or create a project first (top of page).")
        cfg = {
            **self.cfg,
            "provider": provider,
            "gemini_api_key": gkey,
            "gemini_model": gmodel,
            "openrouter_api_key": okey,
            "openrouter_model": omodel,
            "voice": voice,
            "style": style,
        }
        self.cfg.update(cfg)
        proj.data.update({"script": script, "style": style, "aspect": aspect})
        proj.save()
        progress(0.05, desc="splitting script, generating voices")
        planner.plan(proj, cfg, float(target))
        progress(0.95, desc="done")
        preview = planner.preview_voiceover(proj)
        missing = proj.missing_clips()
        extra = (
            f" Still missing clips: {missing}." if missing
            else " All clips present - ready to Assemble!"
        )
        return (
            f"Planned **{len(proj.data['scenes'])} scenes**.{extra} "
            "Copy each prompt below into your video generator.",
            self._plan_rows(proj),
            str(preview) if preview else None,
            str(proj.dir / "shot_list.md"),
            str(proj.clips_dir),
            self._clip_rows(proj),
        )

    def _do_regen(self, proj, num, progress=gr.Progress()):
        if proj is None:
            raise RuntimeError("Open or create a project first.")
        msg = planner.regenerate_scene_audio(proj, int(num))
        preview = planner.preview_voiceover(proj)
        return msg, self._plan_rows(proj), str(preview) if preview else None

    def _do_refresh(self, proj):
        if proj is None:
            raise RuntimeError("Open or create a project first.")
        return str(proj.clips_dir), self._clip_rows(proj)

    def _do_upload(self, proj, files):
        if proj is None:
            raise RuntimeError("Open or create a project first.")
        msg = planner.import_uploaded_clips(proj, files or [])
        missing = proj.missing_clips()
        extra = f" Still missing: {missing}." if missing else " All clips present!"
        return msg + extra, str(proj.clips_dir), self._clip_rows(proj)

    def _do_build(self, proj, transition, trans_dur, tail, bgm, bgmv,
                  progress=gr.Progress()):
        if proj is None:
            raise RuntimeError("Open or create a project first (top of page).")
        missing = proj.missing_clips()
        if missing:
            raise RuntimeError(
                "Clips still missing for scene(s): "
                + ", ".join(str(i) for i in missing)
                + ". Add them in the Shoot tab first."
            )
        progress(0, desc="rendering")
        out, total = assembler.assemble(
            proj,
            {"fps": 30},
            proj.data.get("aspect") or "16:9 (landscape)",
            transition,
            float(trans_dur),
            float(tail),
            bgm,
            float(bgmv),
            progress_cb=lambda frac: progress(float(frac)),
        )
        progress(1.0, desc="done")
        return f"Done - **{total:.1f}s** video saved to `{out}`.", str(out)


def main():
    Ui().build().launch(inbrowser=True, theme=gr.themes.Soft())


if __name__ == "__main__":
    main()
