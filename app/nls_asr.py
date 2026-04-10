"""阿里云实时语音识别（NLS），基于官方 SDK： https://github.com/aliyun/alibabacloud-nls-python-sdk"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from urllib.parse import urlencode
from typing import Any, Callable

import httpx

from app.config import get_nls_settings, nls_configured

logger = logging.getLogger(__name__)

_token_cache: tuple[str, float] | None = None
_TOKEN_TTL_SEC = 50 * 60


def _import_nls() -> Any:
    try:
        import nls  # type: ignore
        from nls.token import getToken  # type: ignore

        return nls, getToken
    except ImportError as e:
        raise RuntimeError(
            "未安装阿里云 NLS Python SDK。请执行：\n"
            "  pip install git+https://github.com/aliyun/alibabacloud-nls-python-sdk.git@dev\n"
            "官方说明见：https://github.com/aliyun/alibabacloud-nls-python-sdk"
        ) from e


def get_nls_token() -> str:
    global _token_cache
    nls_mod, getToken = _import_nls()
    _ = nls_mod  # noqa: F841
    if not nls_configured():
        raise RuntimeError(
            "请在 .env 中配置 NLS_ACCESS_KEY_ID、NLS_ACCESS_KEY_SECRET、NLS_APP_KEY（智能语音交互项目 AppKey）"
        )
    now = time.time()
    if _token_cache and now < _token_cache[1]:
        return _token_cache[0]
    s = get_nls_settings()
    tid = getToken(s.access_key_id, s.access_key_secret, domain=s.token_region)
    _token_cache = (tid, now + _TOKEN_TTL_SEC)
    return tid


def nls_message_text(message: str) -> str:
    try:
        j = json.loads(message)
        p = j.get("payload") or {}
        r = p.get("result")
        if isinstance(r, str):
            return r.strip()
        if isinstance(r, dict):
            return str(r.get("text") or r.get("raw_result") or "").strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return ""


def _extract_text_from_flash_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("payload", "result", "flash_result", "sentence", "sentences"):
            text = _extract_text_from_flash_payload(value.get(key))
            if text:
                return text
        for key in ("text", "raw_result", "transcript", "sentence_text"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(value, list):
        for item in value:
            text = _extract_text_from_flash_payload(item)
            if text:
                return text
    return ""


def flash_recognize_http(
    audio: bytes,
    *,
    aformat: str = "wav",
    sample_rate: int = 16000,
) -> dict[str, Any]:
    if not nls_configured():
        raise RuntimeError("NLS 未配置")

    s = get_nls_settings()
    token = get_nls_token()
    query = urlencode(
        {
            "appkey": s.app_key,
            "token": token,
            "format": aformat,
            "sample_rate": sample_rate,
        }
    )
    url = f"{s.flash_url}?{query}"

    with httpx.Client(timeout=180.0) as client:
        resp = client.post(url, content=audio, headers={"Content-Type": "application/octet-stream"})

    status = resp.status_code
    body_text = resp.text
    if status >= 400:
        snippet = body_text[:500]
        raise RuntimeError(f"FlashRecognizer HTTP {status}: {snippet}")

    raw: Any
    text = ""
    try:
        payload = resp.json()
        raw = payload
        text = _extract_text_from_flash_payload(payload)
    except json.JSONDecodeError:
        raw = body_text

    task_id = (
        resp.headers.get("task_id")
        or resp.headers.get("task-id")
        or resp.headers.get("x-task-id")
        or (
            str(raw.get("task_id") or raw.get("taskId") or "").strip()
            if isinstance(raw, dict)
            else ""
        )
    )

    return {
        "text": text,
        "task_id": task_id,
        "raw": raw,
        "http_status": status,
    }


def recognize_once(
    audio: bytes,
    *,
    aformat: str = "pcm",
    sample_rate: int = 16000,
    enable_intermediate_result: bool = False,
) -> str:
    """一句话识别：整段音频发送完毕后返回最终文本（适合短录音 / 文件上传）。"""
    nls, _ = _import_nls()
    if not nls_configured():
        raise RuntimeError("NLS 未配置")

    s = get_nls_settings()
    holder: dict[str, Any] = {"text": "", "err": None}

    def on_completed(message: str, *_: Any) -> None:
        t = nls_message_text(message)
        if t:
            holder["text"] = t

    def on_error(message: str, *_: Any) -> None:
        holder["err"] = message

    sr = nls.NlsSpeechRecognizer(
        url=s.gateway_url,
        token=get_nls_token(),
        appkey=s.app_key,
        on_completed=on_completed,
        on_error=on_error,
    )
    sr.start(
        aformat=aformat,
        sample_rate=sample_rate,
        ch=1,
        enable_intermediate_result=enable_intermediate_result,
        enable_punctuation_prediction=True,
        enable_inverse_text_normalization=True,
    )
    chunk_sz = 640
    for i in range(0, len(audio), chunk_sz):
        sr.send_audio(audio[i : i + chunk_sz])
    sr.stop()
    if holder["err"]:
        raise RuntimeError(holder["err"])
    return holder["text"]


def blocking_queue_get(q: queue.Queue[tuple[str, str]], timeout: float) -> tuple[str, str] | None:
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


def run_realtime_transcriber(
    audio_q: queue.Queue[bytes | None],
    result_q: queue.Queue[tuple[str, str]],
    stop_flag: threading.Event,
    *,
    aformat: str,
    sample_rate: int,
    enable_intermediate: bool,
) -> None:
    """在独立线程中运行实时转写；audio_q 收到 None 或 stop_flag 置位后结束并 stop()。"""
    nls, _ = _import_nls()
    if not nls_configured():
        result_q.put(("error", "NLS 未配置"))
        result_q.put(("_done_", ""))
        return

    s = get_nls_settings()

    def push(kind: str, text: str) -> None:
        if text or kind == "error":
            result_q.put((kind, text))

    def on_result_changed(message: str, *_: Any) -> None:
        if enable_intermediate:
            t = nls_message_text(message)
            if t:
                push("partial", t)

    def on_sentence_end(message: str, *_: Any) -> None:
        t = nls_message_text(message)
        if t:
            push("sentence", t)

    def on_completed(message: str, *_: Any) -> None:
        t = nls_message_text(message)
        push("completed", t)
        result_q.put(("_done_", ""))

    def on_error(message: str, *_: Any) -> None:
        push("error", message)
        result_q.put(("_done_", ""))

    sr = nls.NlsSpeechTranscriber(
        url=s.gateway_url,
        token=get_nls_token(),
        appkey=s.app_key,
        on_result_changed=on_result_changed if enable_intermediate else None,
        on_sentence_end=on_sentence_end,
        on_completed=on_completed,
        on_error=on_error,
    )
    try:
        sr.start(
            aformat=aformat,
            sample_rate=sample_rate,
            ch=1,
            enable_intermediate_result=enable_intermediate,
            enable_punctuation_prediction=True,
            enable_inverse_text_normalization=True,
        )
        while True:
            try:
                chunk = audio_q.get(timeout=0.25)
            except queue.Empty:
                if stop_flag.is_set():
                    break
                continue
            if chunk is None:
                break
            sr.send_audio(chunk)
        sr.stop()
    except Exception as e:
        logger.exception("NLS transcriber failed")
        push("error", str(e))
        result_q.put(("_done_", ""))
        try:
            sr.shutdown()
        except Exception:
            pass
