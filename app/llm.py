import time
from typing import Any

import httpx

from app.config import ProviderId
from app.models_yaml import resolve_provider_model


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
