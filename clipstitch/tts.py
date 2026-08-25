import asyncio
from pathlib import Path

import edge_tts

PRESET_VOICES = [
    "en-US-AvaNeural",
    "en-US-AndrewNeural",
    "en-US-EmmaNeural",
    "en-US-BrianNeural",
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-IE-EmilyNeural",
]


def list_voices() -> list[str]:
    try:
        voices = asyncio.run(edge_tts.list_voices())
        en = sorted(v["ShortName"] for v in voices if v["Locale"].startswith("en"))
        if en:
            return en
    except Exception:
        pass
    return list(PRESET_VOICES)


def synthesize(text: str, voice: str, out_path: Path, rate: str = "+0%") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        await communicate.save(str(out_path))

    try:
        asyncio.run(run())
    except Exception as exc:
        raise RuntimeError(
            f"Text-to-speech failed ({exc}). Check your internet connection; "
            "edge-tts needs online access to Microsoft's free TTS service."
        ) from exc
