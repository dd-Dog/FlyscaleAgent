import asyncio
import base64
import logging
import queue
import threading
import time
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Optional
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from app import llm, store, tts
from app import nls_asr
from app.audio_util import check_audio_duration
from app.auth import (
    admin_login_configured,
    api_key_configured,
    client_api_key_ok,
    require_admin_session,
    validate_admin_credentials,
    verify_client_api_key,
)
from app.config import ProviderId, get_app_settings, nls_configured
from app.models_yaml import (
    get_models_document,
    list_chat_presets_for_admin,
    list_chat_preset_summaries,
    resolve_chat_system,
)
from app.llm_trace import ensure_tool_trace_logging
from app.tool_intent import should_offer_tools

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = _ROOT / "templates"

_settings = get_app_settings()
app = FastAPI(title="FlyAgent", version="0.1.0")

_secret = _settings.session_secret.strip() or "flyagent-dev-insecure-change-me"
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret,
    same_site="lax",
    https_only=False,
    max_age=86400 * 7,
)


@app.on_event("startup")
def _startup() -> None:
    store.init_db()
    get_models_document()
    ensure_tool_trace_logging()
    s = get_app_settings()
    if admin_login_configured() and not s.session_secret.strip():
        raise RuntimeError(
            "已配置 FLYAGENT_ADMIN_USER / FLYAGENT_ADMIN_PASSWORD 时，必须设置 FLYAGENT_SESSION_SECRET（随机长字符串）"
        )
    if api_key_configured():
        logger.info("HTTP API 已启用 API Key 校验")
    if admin_login_configured():
        logger.info("管理页面已启用登录验证")


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=16000)
    provider: Optional[ProviderId] = None
    # models.yaml chat_prompts 中的 id；与 system_prompt 二选一优先用后者（非空时）
    preset: Optional[str] = Field(default=None, max_length=64)
    system_prompt: Optional[str] = None
    include_audio: bool = True
    # None：全局 FLYAGENT_TOOLS_ENABLED + 关键词轻判；True：强制允许工具；False：禁用工具
    use_tools: Optional[bool] = None


class AdminDefaultBody(BaseModel):
    default_provider: ProviderId


class AdminDefaultChatPresetBody(BaseModel):
    preset: str = Field(default="", max_length=64)


class AdminLoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class TtsBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: Optional[str] = Field(default=None, max_length=64)


def _read_template(name: str) -> str:
    return (_TEMPLATES / name).read_text(encoding="utf-8")


@app.post("/api/chat")
async def api_chat(
    body: ChatBody,
    _: Annotated[None, Depends(verify_client_api_key)],
) -> JSONResponse:
    settings = get_app_settings()
    provider = body.provider or store.get_default_provider()
    try:
        sys_p, preset_used = resolve_chat_system(
            request_system=body.system_prompt,
            request_preset=body.preset,
            default_preset_id=store.get_default_chat_preset(),
            global_system=settings.system_prompt,
        )
    except KeyError as e:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 preset: {e.args[0]}，可用 id 见 GET /api/presets",
        ) from e

    if body.use_tools is False:
        offer_tools = False
    elif body.use_tools is True:
        offer_tools = settings.tools_enabled
    else:
        offer_tools = settings.tools_enabled and should_offer_tools(body.message)

    t0 = time.perf_counter()
    try:
        text, latency_llm, tools_meta = await llm.chat_completion_with_tools(
            provider,
            body.message,
            sys_p,
            offer_tools=offer_tools,
        )
    except Exception as e:
        latency_llm = int((time.perf_counter() - t0) * 1000)
        err = str(e)
        store.log_access(provider, body.message, f"ERROR: {err}", latency_llm, False)
        raise HTTPException(status_code=502, detail=err) from e

    store.log_access(provider, body.message, text, latency_llm, True)

    out: dict[str, Any] = {
        "provider": provider,
        "text": text,
        "latency_ms": latency_llm,
        "preset": preset_used,
        "tools": tools_meta,
    }

    if body.include_audio and text:
        try:
            audio_bytes, mime = await tts.synthesize_speech(text)
            out["audio_base64"] = base64.b64encode(audio_bytes).decode("ascii")
            out["audio_mime"] = mime
        except Exception as e:
            out["audio_error"] = str(e)

    return JSONResponse(out)


@app.get("/api/presets")
async def api_presets() -> dict[str, Any]:
    """列出 chat_prompts 的 id 与名称（不含 system 全文），供客户端选模式。"""
    return {"presets": list_chat_preset_summaries()}


@app.post("/api/tts")
async def api_tts(
    body: TtsBody,
    _: Annotated[None, Depends(verify_client_api_key)],
) -> dict[str, Any]:
    """阿里云在线语音合成：输入文本，输出 base64 音频。"""
    t0 = time.perf_counter()
    try:
        audio_bytes, mime = await tts.synthesize_speech(body.text, body.voice)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_mime": mime,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


@app.post("/api/voice/chat")
async def api_voice_chat(
    _: Annotated[None, Depends(verify_client_api_key)],
    file: UploadFile = File(...),
    asr_engine: str = Query("flash", description="flash | recognize"),
    format: str = Query("wav", description="上传音频格式，如 wav/mp3/pcm"),
    sample_rate: int = Query(16000, ge=8000, le=48000),
    provider: Optional[ProviderId] = Query(None),
    preset: Optional[str] = Query(
        None,
        description="聊天预设；不传时默认 brief（单句回复）",
    ),
    voice: Optional[str] = Query(None, description="TTS 发音人，不传走 NLS_TTS_VOICE"),
    use_tools: Optional[bool] = Query(
        None,
        description="None 走全局与关键词轻判；true/false 强制开关内置工具",
    ),
) -> Response:
    """
    端到端语音 AI：
    上传音频文件 -> 语音识别 -> 大模型一句话回复 -> 语音合成 -> 直接返回音频文件。
    """
    settings = get_app_settings()
    selected_provider = provider or store.get_default_provider()
    body = await file.read()
    if len(body) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频文件过大（>100MB）")
    try:
        check_audio_duration(body, format, sample_rate, settings.audio_max_duration_sec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 1) ASR
    t0 = time.perf_counter()
    try:
        engine = asr_engine.lower().strip()
        if engine == "flash":
            asr_result = await asyncio.to_thread(
                partial(
                    nls_asr.flash_recognize_http,
                    body,
                    aformat=format,
                    sample_rate=sample_rate,
                )
            )
            user_text = str(asr_result.get("text") or "").strip()
        elif engine == "recognize":
            user_text = await asyncio.to_thread(
                partial(
                    nls_asr.recognize_once,
                    body,
                    aformat=format,
                    sample_rate=sample_rate,
                )
            )
            user_text = (user_text or "").strip()
        else:
            raise HTTPException(status_code=400, detail="asr_engine 仅支持 flash 或 recognize")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"ASR 失败: {e}") from e

    if not user_text:
        raise HTTPException(status_code=422, detail="ASR 未识别到有效文本")

    # 2) LLM（默认 brief，满足一句话回复）
    try:
        sys_p, preset_used = resolve_chat_system(
            request_system=None,
            request_preset=(preset or "brief"),
            default_preset_id=store.get_default_chat_preset(),
            global_system=settings.system_prompt,
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"无效 preset: {e.args[0]}") from e

    if use_tools is False:
        offer_tools = False
    elif use_tools is True:
        offer_tools = settings.tools_enabled
    else:
        offer_tools = settings.tools_enabled and should_offer_tools(user_text)

    try:
        answer_text, _, _ = await llm.chat_completion_with_tools(
            selected_provider,
            user_text,
            sys_p,
            offer_tools=offer_tools,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 失败: {e}") from e

    answer_text = (answer_text or "").strip()
    if not answer_text:
        raise HTTPException(status_code=502, detail="LLM 返回空文本")

    # 3) TTS
    try:
        audio_bytes, mime = await tts.synthesize_speech(answer_text, voice)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS 失败: {e}") from e

    total_ms = int((time.perf_counter() - t0) * 1000)
    ext = "mp3" if mime == "audio/mpeg" else ("wav" if mime == "audio/wav" else "pcm")
    headers = {
        "Content-Disposition": f'attachment; filename="voice_reply.{ext}"',
        "X-ASR-Text-UrlEncoded": quote(user_text),
        "X-Reply-Text-UrlEncoded": quote(answer_text),
        "X-Provider": selected_provider,
        "X-Preset": preset_used or "",
        "X-Total-Latency-Ms": str(total_ms),
    }
    return Response(content=audio_bytes, media_type=mime, headers=headers)


@app.get("/api/asr/ready")
async def asr_ready() -> dict[str, Any]:
    """检查 NLS 环境：是否配置密钥、是否已安装官方 SDK。"""
    sdk = True
    try:
        nls_asr._import_nls()
    except RuntimeError:
        sdk = False
    return {"nls_configured": nls_configured(), "sdk_installed": sdk}


@app.post("/api/asr/recognize")
async def asr_recognize(
    _: Annotated[None, Depends(verify_client_api_key)],
    file: UploadFile = File(...),
    format: str = Query("pcm", description="音频格式：pcm / wav / mp3 等"),
    sample_rate: int = Query(16000, ge=8000, le=48000),
) -> dict[str, Any]:
    """
    一句话识别：上传完整音频文件，返回识别文本。
    与实时流式接口相比，适合短录音；长音频也可用但需一次上传完毕。
    """
    if not nls_configured():
        raise HTTPException(status_code=503, detail="未配置 NLS（NLS_ACCESS_KEY_ID 等）")
    body = await file.read()
    if len(body) > 32 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频文件过大（>32MB）")
    try:
        check_audio_duration(body, format, sample_rate, get_app_settings().audio_max_duration_sec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        text = await asyncio.to_thread(
            partial(
                nls_asr.recognize_once,
                body,
                aformat=format,
                sample_rate=sample_rate,
            )
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"text": text, "format": format, "sample_rate": sample_rate}


@app.post("/api/asr/flash")
async def asr_flash(
    _: Annotated[None, Depends(verify_client_api_key)],
    file: UploadFile = File(...),
    format: str = Query("wav", description="音频格式：wav / mp3 / pcm 等"),
    sample_rate: int = Query(16000, ge=8000, le=48000),
) -> dict[str, Any]:
    if not nls_configured():
        raise HTTPException(status_code=503, detail="未配置 NLS（NLS_ACCESS_KEY_ID 等）")

    body = await file.read()
    if len(body) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频文件过大（>100MB）")
    try:
        check_audio_duration(body, format, sample_rate, get_app_settings().audio_max_duration_sec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    t0 = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            partial(
                nls_asr.flash_recognize_http,
                body,
                aformat=format,
                sample_rate=sample_rate,
            )
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    latency_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "text": result.get("text") or "",
        "format": format,
        "sample_rate": sample_rate,
        "latency_ms": latency_ms,
        "task_id": result.get("task_id") or "",
        "http_status": result.get("http_status"),
    }


@app.websocket("/api/asr/stream")
async def asr_stream(
    websocket: WebSocket,
    aformat: str = Query("pcm"),
    sample_rate: int = Query(16000, ge=8000, le=48000),
    intermediate: bool = Query(True),
    api_key: str | None = Query(None),
) -> None:
    """
    实时语音识别（WebSocket）：客户端持续发送二进制音频帧（与 `aformat`/`sample_rate` 一致），
    服务端推送 JSON：`{type: partial|sentence|completed|error, text: string}`。
    客户端结束请 **关闭 WebSocket**；若启用了 FLYAGENT_API_KEY，可传 query `api_key=` 或 header `X-API-Key`。
    """
    await websocket.accept()
    s_app = get_app_settings()
    if s_app.api_key.strip():
        hdr = websocket.headers.get("x-api-key") or websocket.headers.get("X-API-Key")
        if not client_api_key_ok(api_key or hdr):
            await websocket.close(code=4000, reason="Invalid API key")
            return

    if not nls_configured():
        await websocket.send_json({"type": "error", "text": "未配置 NLS（.env 中 NLS_ACCESS_KEY_ID 等）"})
        await websocket.close(code=4002)
        return

    try:
        nls_asr._import_nls()
    except RuntimeError as e:
        await websocket.send_json({"type": "error", "text": str(e)})
        await websocket.close(code=4001)
        return

    audio_q: queue.Queue[bytes | None] = queue.Queue()
    result_q: queue.Queue[tuple[str, str]] = queue.Queue()
    stop_flag = threading.Event()

    th = threading.Thread(
        target=partial(
            nls_asr.run_realtime_transcriber,
            audio_q,
            result_q,
            stop_flag,
            aformat=aformat,
            sample_rate=sample_rate,
            enable_intermediate=intermediate,
        ),
        daemon=True,
    )
    th.start()

    async def recv_loop() -> None:
        try:
            while True:
                msg = await websocket.receive()
                mtype = msg.get("type")
                if mtype == "websocket.disconnect":
                    break
                if mtype == "websocket.receive":
                    b = msg.get("bytes")
                    if b:
                        audio_q.put(b)
        except WebSocketDisconnect:
            pass
        finally:
            stop_flag.set()
            try:
                audio_q.put_nowait(None)
            except queue.Full:
                pass

    async def forward_loop() -> None:
        while True:
            item = await asyncio.to_thread(nls_asr.blocking_queue_get, result_q, 0.4)
            if item is None:
                if not th.is_alive() and result_q.empty():
                    break
                continue
            kind, text = item
            if kind == "_done_":
                break
            await websocket.send_json({"type": kind, "text": text})

    recv_task = asyncio.create_task(recv_loop())
    forward_task = asyncio.create_task(forward_loop())
    try:
        done, pending = await asyncio.wait(
            {recv_task, forward_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if forward_task in done:
            recv_task.cancel()
        else:
            try:
                await asyncio.wait_for(forward_task, timeout=120)
            except asyncio.TimeoutError:
                forward_task.cancel()
        await asyncio.gather(recv_task, forward_task, return_exceptions=True)
    finally:
        th.join(timeout=90)
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/admin/session")
async def admin_session(request: Request) -> dict[str, Any]:
    if not admin_login_configured():
        return {"auth_required": False, "authenticated": True}
    return {
        "auth_required": True,
        "authenticated": bool(request.session.get("admin")),
    }


@app.post("/api/admin/login")
async def admin_login(request: Request, body: AdminLoginBody) -> dict[str, bool]:
    if not admin_login_configured():
        raise HTTPException(status_code=400, detail="未配置管理端登录，无需登录")
    if not validate_admin_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    request.session["admin"] = True
    return {"ok": True}


@app.post("/api/admin/logout")
async def admin_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.get("/api/admin/summary")
async def admin_summary(
    _: Annotated[None, Depends(require_admin_session)],
) -> dict[str, Any]:
    st = store.stats()
    return {
        "default_provider": store.get_default_provider(),
        "default_chat_preset": store.get_default_chat_preset(),
        "stats": st,
    }


@app.get("/api/admin/recent")
async def admin_recent(
    _: Annotated[None, Depends(require_admin_session)],
    limit: int = 50,
) -> dict[str, Any]:
    return {"records": store.recent_records(min(limit, 200))}


@app.post("/api/admin/default_provider")
async def admin_set_default(
    body: AdminDefaultBody,
    _: Annotated[None, Depends(require_admin_session)],
) -> dict[str, str]:
    store.set_default_provider(body.default_provider)
    return {"default_provider": body.default_provider}


@app.get("/api/admin/prompts")
async def admin_prompts(
    _: Annotated[None, Depends(require_admin_session)],
) -> dict[str, Any]:
    return {"presets": list_chat_presets_for_admin()}


@app.post("/api/admin/default_chat_preset")
async def admin_set_default_chat_preset(
    body: AdminDefaultChatPresetBody,
    _: Annotated[None, Depends(require_admin_session)],
) -> dict[str, str]:
    try:
        store.set_default_chat_preset(body.preset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"default_chat_preset": store.get_default_chat_preset()}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if admin_login_configured() and request.session.get("admin"):
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse(_read_template("login.html"))


@app.get("/", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    if admin_login_configured() and not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(_read_template("admin.html"))

