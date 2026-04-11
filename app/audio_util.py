"""根据上传音频字节估算时长，用于限制最大录音长度。"""

from __future__ import annotations

import io
import logging
import wave
from typing import Optional

logger = logging.getLogger(__name__)


def estimate_audio_duration_sec(data: bytes, fmt: str, sample_rate: int) -> Optional[float]:
    """
    返回估算时长（秒）；无法识别格式时返回 None（此时不强制时长，依赖其它大小限制）。
    pcm 按 mono 16-bit little-endian 估算（与常见 ASR 上传一致）。
    """
    if not data:
        return 0.0
    f = (fmt or "").lower().strip()

    if f == "wav":
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or sample_rate
                if rate <= 0:
                    return None
                return frames / float(rate)
        except Exception as e:
            logger.debug("wav duration parse failed: %s", e)
            return None

    if f in ("pcm", "raw", "s16le"):
        if sample_rate <= 0:
            return None
        return len(data) / float(sample_rate * 2)

    if f == "mp3":
        try:
            from mutagen.mp3 import MP3  # type: ignore

            info = MP3(io.BytesIO(data)).info
            if info.length and info.length > 0:
                return float(info.length)
        except Exception as e:
            logger.debug("mp3 duration via mutagen failed: %s", e)
        # 粗算：按 128kbps 估上限偏保守
        return len(data) * 8 / 128_000.0

    return None


def check_audio_duration(data: bytes, fmt: str, sample_rate: int, max_sec: int) -> None:
    """超过 max_sec 则抛出 ValueError（供路由层转为 400）。"""
    if max_sec <= 0:
        return
    d = estimate_audio_duration_sec(data, fmt, sample_rate)
    if d is None:
        return
    if d > max_sec + 0.5:
        raise ValueError(f"音频时长超过限制（最长 {max_sec} 秒，当前约 {d:.1f} 秒）")
