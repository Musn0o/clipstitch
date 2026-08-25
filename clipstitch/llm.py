import difflib
import json
import re

import httpx

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE = "https://openrouter.ai/api/v1/"
REQUEST_TIMEOUT = 90.0

SYSTEM_TEMPLATE = """You are a film storyboard planner for short videos made of AI-generated clips.

Split the narrator's script into a sequence of scenes.

Rules:
1. The narration fields, joined in order, must reproduce the script VERBATIM: same words, same order, nothing added, removed or rephrased. Only whitespace may differ.
2. Each scene's narration should take about {target} seconds to speak (roughly {words} words). Never exceed {max_words} words in one scene.
3. Split at natural story beats so each scene shows one clear visual moment.
4. The prompt describes only what we SEE on screen: subject, action, setting, lighting, mood and one camera move, in present tense. Never include dialogue, speech bubbles or on-screen text requests.
5. Keep ONE consistent cinematic style across every prompt. Repeat the style keywords verbatim in each prompt.{style_line}
6. If a character appears in multiple scenes, repeat the exact same character description in every prompt.

Answer with ONLY valid JSON, no markdown fences:
{{"scenes": [{{"narration": "...", "prompt": "..."}}]}}"""


class LlmError(RuntimeError):
    pass


def _candidates(cfg: dict) -> list[tuple[str, str, str, str]]:
    out = []
    provider = cfg.get("provider", "auto")
    gemini_ok = bool(cfg.get("gemini_api_key"))
    openrouter_ok = bool(cfg.get("openrouter_api_key"))
    if provider in ("auto", "gemini") and gemini_ok:
        out.append(("gemini", GEMINI_BASE, cfg["gemini_api_key"], cfg.get("gemini_model", "")))
    if provider in ("auto", "openrouter") and openrouter_ok:
        out.append(
            ("openrouter", OPENROUTER_BASE, cfg["openrouter_api_key"], cfg.get("openrouter_model", ""))
        )
    return out


def _extract_json(content: str):
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _call_llm(base_url: str, api_key: str, model: str, system: str, user: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://localhost.clipstitch"
        headers["X-Title"] = "ClipStitch"
    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise LlmError(f"API error {response.status_code}: {response.text[:300]}")
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content)
    return content


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _validate(scenes: list[dict], script: str) -> None:
    joined = _normalize(" ".join(s.get("narration", "") for s in scenes))
    original = _normalize(script)
    ratio = difflib.SequenceMatcher(None, joined, original).ratio()
    if ratio < 0.92:
        raise LlmError(
            f"The model rewrote the script instead of splitting it (match {ratio:.0%}). "
            "Try again, pick a different model, or use the Manual split provider."
        )
    for i, scene in enumerate(scenes, 1):
        if not scene.get("narration") or not scene.get("prompt"):
            raise LlmError(f"Scene {i} came back incomplete. Try again or use Manual split.")


def split_scenes(script: str, cfg: dict, target_seconds: float = 5.0) -> list[dict]:
    words_per_second = 2.7
    words = max(6, round(target_seconds * words_per_second))
    system = SYSTEM_TEMPLATE.format(
        target=target_seconds,
        words=words,
        max_words=words + 4,
        style_line=(
            f"\n   The user's requested style: {cfg.get('style', '').strip()}"
            if cfg.get("style", "").strip()
            else ""
        ),
    )
    candidates = _candidates(cfg)
    errors = []
    for name, base, key, model in candidates:
        try:
            content = _call_llm(base, key, model, system, script.strip())
            data = _extract_json(content)
            scenes = data["scenes"]
            if not isinstance(scenes, list) or not scenes:
                raise LlmError("Model returned no scenes.")
            scenes = [
                {"index": i, "narration": s["narration"].strip(), "prompt": s["prompt"].strip()}
                for i, s in enumerate(scenes, 1)
            ]
            _validate(scenes, script)
            return scenes
        except Exception as exc:
            errors.append(f"{name}/{model}: {exc}")
    raise RuntimeError(
        "Automatic scene planning failed.\n"
        + "\n".join(errors)
        + "\n\nYou can still continue: set Provider to 'manual' to split the script by blank lines."
    )


def manual_split(script: str, target_seconds: float = 5.0) -> list[dict]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", script.strip()) if p.strip()]
    chunks = []
    if len(paragraphs) > 1:
        chunks = paragraphs
    else:
        sentences = re.split(r"(?<=[.!?])\s+", script.replace("\n", " ").strip())
        current = []
        current_words = 0
        budget = max(8, round(target_seconds * 2.7))
        for sentence in sentences:
            sentence_words = len(sentence.split())
            if current and current_words + sentence_words > budget:
                chunks.append(" ".join(current))
                current, current_words = [], 0
            current.append(sentence)
            current_words += sentence_words
        if current:
            chunks.append(" ".join(current))
    if not chunks and paragraphs:
        chunks = paragraphs
    return [
        {"index": i, "narration": chunk, "prompt": ""}
        for i, chunk in enumerate(chunks, 1)
    ]
