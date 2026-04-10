import asyncio
from typing import Any

from app.config import get_nls_settings, nls_configured
from app.nls_asr import _import_nls, get_nls_token


def _mime_from_format(aformat: str) -> str:
    fmt = aformat.lower().strip()
    if fmt == "mp3":
        return "audio/mpeg"
    if fmt == "wav":
        return "audio/wav"
    return "audio/pcm"


def _synthesize_sync(text: str, voice: str | None = None) -> tuple[bytes, str]:
    if not nls_configured():
        raise RuntimeError("未配置 NLS，无法使用阿里云语音合成")
    nls, _ = _import_nls()
    s = get_nls_settings()

    out = bytearray()
    err: dict[str, str] = {"msg": ""}

    def on_data(data: bytes, *_: Any) -> None:
        out.extend(data)

    def on_error(message: str, *_: Any) -> None:
        err["msg"] = message

    syn = nls.NlsSpeechSynthesizer(
        url=s.gateway_url,
        token=get_nls_token(),
        appkey=s.app_key,
        on_data=on_data,
        on_error=on_error,
    )
    syn.start(
        text=text,
        voice=(voice or "").strip() or s.tts_voice,
        aformat=s.tts_format,
        sample_rate=s.tts_sample_rate,
        volume=s.tts_volume,
        speech_rate=s.tts_speech_rate,
        pitch_rate=s.tts_pitch_rate,
        wait_complete=True,
        start_timeout=10,
        completed_timeout=120,
    )
    if err["msg"]:
        raise RuntimeError(err["msg"])
    return bytes(out), _mime_from_format(s.tts_format)


async def synthesize_speech(text: str, voice: str | None = None) -> tuple[bytes, str]:
    """Return (audio_bytes, mime_type)."""
    return await asyncio.to_thread(_synthesize_sync, text, voice)
