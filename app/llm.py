import json
import logging
import time
import uuid
from typing import Any

import httpx

from app.builtin_tools import get_builtin_tool_schemas, run_builtin_tool
from app.config import ProviderId, get_app_settings
from app.llm_trace import trace_logger
from app.models_yaml import resolve_provider_model
from app.tool_tier1 import analyze_tier1

_tlog = trace_logger()

_TOOL_SYSTEM_SUFFIX = (
    "\n\n【工具策略】当用户需要实时天气、新闻头条或航班/机票等行程信息时，使用提供的工具；"
    "闲聊、常识、解题、翻译等不要调用工具。航班工具若返回未配置下游，请如实说明并建议官方购票渠道。"
    "\n【效率】同一用户问题内，每种工具尽量只调用一次；天气工具若已返回有效预报数据，不要因「区县级地名」再换城市名重复调用。"
)


def _clip(text: str, limit: int = 280) -> str:
    t = (text or "").replace("\r", "").replace("\n", " ")
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 3)] + "..."


def _messages_digest(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.get("role") or "?"
        if role == "tool":
            c = m.get("content") or ""
            parts.append(f"tool({len(c)}ch)")
        elif role == "assistant" and m.get("tool_calls"):
            n = len(m["tool_calls"]) if isinstance(m["tool_calls"], list) else 0
            parts.append(f"assistant+{n}calls")
        else:
            c = m.get("content") or ""
            parts.append(f"{role}({len(c)}ch)")
    return " -> ".join(parts)


async def _openai_compatible_chat(
    base: str,
    api_key: str,
    model: str,
    user_text: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int | None,
    extra_headers: dict[str, str],
) -> tuple[str, int]:
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": user_text})

    url = f"{base.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **extra_headers,
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload, headers=headers)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"模型 API 错误 {r.status_code}: {detail}")

    data = r.json()
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"无法解析模型响应: {data}") from e

    return text.strip(), latency_ms


async def _anthropic_messages(
    api_base: str,
    api_key: str,
    model: str,
    user_text: str,
    system_prompt: str,
    max_tokens: int,
    api_version: str,
) -> tuple[str, int]:
    url = f"{api_base.rstrip('/')}/v1/messages"
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_text}],
    }
    if system_prompt.strip():
        body["system"] = system_prompt.strip()

    headers = {
        "x-api-key": api_key,
        "anthropic-version": api_version,
        "Content-Type": "application/json",
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=body, headers=headers)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Claude API 错误 {r.status_code}: {detail}")

    data = r.json()
    try:
        parts: list[str] = []
        for block in data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        text = "".join(parts).strip()
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"无法解析 Claude 响应: {data}") from e

    if not text:
        raise RuntimeError(f"Claude 返回空内容: {data}")

    return text, latency_ms


async def chat_completion(
    provider: ProviderId,
    user_text: str,
    system_prompt: str,
) -> tuple[str, int]:
    cfg = resolve_provider_model(provider)
    if not cfg.api_key:
        raise ValueError(
            f"未配置 {provider} 的 API 密钥：请在 .env 中设置环境变量 {cfg.api_key_env}（见 models.yaml）"
        )

    if cfg.use_anthropic_messages:
        return await _anthropic_messages(
            cfg.base_url,
            cfg.api_key,
            cfg.model,
            user_text,
            system_prompt,
            cfg.anthropic_max_tokens,
            cfg.anthropic_api_version,
        )

    return await _openai_compatible_chat(
        cfg.base_url,
        cfg.api_key,
        cfg.model,
        user_text,
        system_prompt,
        cfg.temperature,
        cfg.max_tokens,
        cfg.extra_headers,
    )


async def _openai_compatible_chat_messages(
    base: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    extra_headers: dict[str, str],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    trace_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """单次 chat/completions，返回 (response_json, latency_ms)。"""
    url = f"{base.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **extra_headers,
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload, headers=headers)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        if trace_id:
            _tlog.warning(
                "[%s] chat.completions HTTP %s | %s",
                trace_id,
                r.status_code,
                _clip(str(detail), 600),
            )
        raise RuntimeError(f"模型 API 错误 {r.status_code}: {detail}")

    return r.json(), latency_ms


async def chat_completion_with_tools(
    provider: ProviderId,
    user_text: str,
    system_prompt: str,
    *,
    offer_tools: bool,
) -> tuple[str, int, dict[str, Any]]:
    """
    在 OpenAI 兼容接口上执行可选的 tools 循环。
    offer_tools=False 或当前 provider 不支持时，等价于 chat_completion。
    返回 (text, total_latency_ms, meta)。
    """
    cfg = resolve_provider_model(provider)
    if not cfg.api_key:
        raise ValueError(
            f"未配置 {provider} 的 API 密钥：请在 .env 中设置环境变量 {cfg.api_key_env}（见 models.yaml）"
        )

    settings = get_app_settings()
    meta: dict[str, Any] = {
        "tools_offered": False,
        "tool_model_calls": 0,
        "tool_turns_with_calls": 0,
    }

    if cfg.use_anthropic_messages or not settings.tools_enabled or not offer_tools:
        trace_id = uuid.uuid4().hex[:12]
        meta["trace_id"] = trace_id
        _tlog.info(
            "[%s] path=simple_chat provider=%s model=%s offer_tools=%s user=%r",
            trace_id,
            provider,
            cfg.model,
            offer_tools,
            _clip(user_text, 400),
        )
        text, lat = await chat_completion(provider, user_text, system_prompt)
        _tlog.info(
            "[%s] simple_chat done latency_ms=%d reply=%r",
            trace_id,
            lat,
            _clip(text, 500),
        )
        return text, lat, meta

    # 一级规则：命中则服务端先执行工具，再单次 chat（跳过 tool 协议多轮）
    if settings.tools_tier1_enabled:
        tier = analyze_tier1(user_text)
        if tier.prefetch:
            trace_id = uuid.uuid4().hex[:12]
            meta["trace_id"] = trace_id
            _tlog.info(
                "[%s] path=tier1_prefetch kind=%s tool=%s args=%r user=%r",
                trace_id,
                tier.kind,
                tier.tool_name,
                tier.args,
                _clip(user_text, 400),
            )
            t_tool = time.perf_counter()
            raw = await run_builtin_tool(tier.tool_name, tier.args)
            tier1_tool_ms = int((time.perf_counter() - t_tool) * 1000)
            augmented = (
                f"{user_text}\n\n"
                f"【服务端已调用 {tier.tool_name}，工具耗时约 {tier1_tool_ms} ms】\n{raw}\n\n"
                "请严格依据上述 JSON 回答用户，勿编造；若含 error 字段请如实说明。"
            )
            text, lat_llm = await chat_completion(provider, augmented, system_prompt)
            total_ms = lat_llm + tier1_tool_ms
            meta.update(
                {
                    "tools_offered": True,
                    "tier1_prefetch": tier.kind,
                    "tool_loop_skipped": True,
                    "tool_model_calls": 1,
                    "tool_turns_with_calls": 0,
                    "tier1_tool_latency_ms": tier1_tool_ms,
                }
            )
            _tlog.info(
                "[%s] tier1_prefetch done llm_ms=%d tool_ms=%d total_ms=%d reply=%r",
                trace_id,
                lat_llm,
                tier1_tool_ms,
                total_ms,
                _clip(text, 500),
            )
            return text, total_ms, meta

    trace_id = uuid.uuid4().hex[:12]
    meta["trace_id"] = trace_id
    max_calls = settings.tools_max_model_calls
    sys_full = (system_prompt.strip() + _TOOL_SYSTEM_SUFFIX).strip()
    messages: list[dict[str, Any]] = [{"role": "system", "content": sys_full}]
    messages.append({"role": "user", "content": user_text})

    total_latency = 0
    meta["tools_offered"] = True

    _tlog.info(
        "[%s] path=tool_loop start provider=%s model=%s max_calls=%d user=%r",
        trace_id,
        provider,
        cfg.model,
        max_calls,
        _clip(user_text, 400),
    )

    for call_idx in range(max_calls):
        include_tools = call_idx < max_calls - 1
        tools = get_builtin_tool_schemas() if include_tools else None
        tool_choice = "auto" if include_tools else None

        _tlog.info(
            "[%s] --> llm_request #%d/%d tools=%s tool_choice=%s | ctx=%s",
            trace_id,
            call_idx + 1,
            max_calls,
            bool(tools),
            tool_choice or "(none)",
            _messages_digest(messages),
        )
        if _tlog.isEnabledFor(logging.DEBUG):
            _tlog.debug("[%s] messages_json=%s", trace_id, json.dumps(messages, ensure_ascii=False)[:8000])

        data, lat = await _openai_compatible_chat_messages(
            cfg.base_url,
            cfg.api_key,
            cfg.model,
            messages,
            cfg.temperature,
            cfg.max_tokens,
            cfg.extra_headers,
            tools=tools,
            tool_choice=tool_choice,
            trace_id=trace_id,
        )
        total_latency += lat
        meta["tool_model_calls"] = call_idx + 1

        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError) as e:
            _tlog.error("[%s] parse_response_failed data_keys=%s", trace_id, list(data.keys()) if isinstance(data, dict) else type(data))
            raise RuntimeError(f"无法解析模型响应: {data}") from e

        finish_reason = choice.get("finish_reason")
        tool_calls = msg.get("tool_calls")
        content = (msg.get("content") or "").strip()

        _tlog.info(
            "[%s] <-- llm_response #%d latency_ms=%d finish_reason=%r content_preview=%r tool_calls=%s",
            trace_id,
            call_idx + 1,
            lat,
            finish_reason,
            _clip(content, 320),
            len(tool_calls) if isinstance(tool_calls, list) else 0,
        )

        if tool_calls and include_tools:
            meta["tool_turns_with_calls"] += 1
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                tname = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else {}
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                _tlog.info(
                    "[%s] .... tool_execute name=%s call_id=%s args=%r",
                    trace_id,
                    tname,
                    tc.get("id"),
                    _clip(json.dumps(args, ensure_ascii=False), 400),
                )
                result = await run_builtin_tool(str(tname), args)
                _tlog.info(
                    "[%s] .... tool_result name=%s chars=%d preview=%r",
                    trace_id,
                    tname,
                    len(result),
                    _clip(result, 500),
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or "",
                        "content": result,
                    }
                )
            continue

        if content:
            _tlog.info(
                "[%s] path=tool_loop end ok total_latency_ms=%d rounds=%d",
                trace_id,
                total_latency,
                call_idx + 1,
            )
            return content, total_latency, meta

        # 无文本仅有 tool_calls 但已是最后一轮（不应再调工具）
        if tool_calls and not include_tools:
            _tlog.warning(
                "[%s] last_round_had_tool_calls; nudge_user no_tools",
                trace_id,
            )
            messages.append(
                {
                    "role": "user",
                    "content": "请直接根据上文给出最终中文回答，勿再调用工具。",
                }
            )
            continue

        if not tool_calls:
            _tlog.info(
                "[%s] path=tool_loop end empty_content total_latency_ms=%d",
                trace_id,
                total_latency,
            )
            return content or "", total_latency, meta

    err = f"工具循环超过最大模型调用次数（{max_calls}），请在配置中增大 FLYAGENT_TOOLS_MAX_MODEL_CALLS"
    _tlog.error("[%s] %s", trace_id, err)
    raise RuntimeError(err)
