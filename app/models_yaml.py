"""Load LLM endpoints, models and api_key_env from models.yaml; API keys from process env (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import ProviderId, get_app_settings


# FlyAgent API provider -> key under models.yaml `models`
PROVIDER_YAML_KEY: dict[ProviderId, str] = {
    "doubao": "doubao",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "kimi": "kimi",
    "openai": "openai",
    "claude": "claude",
    "gemini": "gemini",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def models_yaml_path() -> Path:
    p = Path(get_app_settings().models_path)
    if not p.is_absolute():
        p = _project_root() / p
    return p


@lru_cache(maxsize=8)
def _load_document(path_str: str, mtime: float) -> dict[str, Any]:
    with open(path_str, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def get_models_document() -> dict[str, Any]:
    path = models_yaml_path()
    if not path.is_file():
        raise FileNotFoundError(f"未找到大模型配置文件: {path}")
    return _load_document(str(path.resolve()), path.stat().st_mtime)


@dataclass(frozen=True)
class ResolvedModelConfig:
    base_url: str
    api_key: str
    model: str
    api_key_env: str
    temperature: float
    max_tokens: int | None
    extra_headers: dict[str, str]
    use_anthropic_messages: bool
    anthropic_api_version: str
    anthropic_max_tokens: int


def _infer_anthropic_native(entry: dict[str, Any], base_url: str) -> bool:
    proto = (entry.get("protocol") or "").strip().lower()
    if proto == "anthropic_messages":
        return True
    if proto == "openai_compat":
        return False
    return "api.anthropic.com" in base_url.lower()


def resolve_provider_model(provider: ProviderId) -> ResolvedModelConfig:
    doc = get_models_document()
    models = doc.get("models")
    if not isinstance(models, dict):
        raise ValueError("models.yaml 缺少有效的 models 映射")

    key = PROVIDER_YAML_KEY[provider]
    entry = models.get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"models.yaml 的 models 下缺少条目: {key}")

    if entry.get("enabled") is False:
        raise ValueError(f"models.{key} 已禁用 (enabled: false)")

    api_key_env = entry.get("api_key_env")
    if not api_key_env or not isinstance(api_key_env, str):
        raise ValueError(f"models.{key} 缺少 api_key_env")
    api_key = os.environ.get(api_key_env.strip(), "")

    base_url = (entry.get("base_url") or "").strip().rstrip("/")
    model = (entry.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError(f"models.{key} 缺少 base_url 或 model")

    params_raw = entry.get("params")
    params: dict[str, Any] = dict(params_raw) if isinstance(params_raw, dict) else {}

    temperature = float(params.get("temperature", 0.7))
    max_tokens = params.get("max_tokens")
    max_tokens_i = int(max_tokens) if max_tokens is not None else None

    extra: dict[str, str] = {}
    if hr := params.get("http_referer"):
        extra["HTTP-Referer"] = str(hr)
    if xt := params.get("x_title"):
        extra["X-Title"] = str(xt)

    use_native = _infer_anthropic_native(entry, base_url)
    anthropic_ver = str(entry.get("anthropic_api_version") or "2023-06-01")
    anthropic_max = int(entry.get("anthropic_max_tokens") or params.get("max_tokens") or 4096)

    return ResolvedModelConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        api_key_env=api_key_env.strip(),
        temperature=temperature,
        max_tokens=max_tokens_i,
        extra_headers=extra,
        use_anthropic_messages=use_native and provider == "claude",
        anthropic_api_version=anthropic_ver,
        anthropic_max_tokens=anthropic_max,
    )


def get_chat_prompts() -> dict[str, dict[str, Any]]:
    doc = get_models_document()
    raw = doc.get("chat_prompts")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for pid, v in raw.items():
        if not isinstance(v, dict):
            continue
        if v.get("enabled") is False:
            continue
        sys_t = v.get("system")
        if not isinstance(sys_t, str) or not sys_t.strip():
            continue
        out[str(pid)] = v
    return out


def get_preset_system(preset_id: str) -> str | None:
    entry = get_chat_prompts().get(preset_id.strip())
    if not entry:
        return None
    return (entry.get("system") or "").strip()


def list_chat_presets_for_admin() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for pid, v in sorted(get_chat_prompts().items()):
        name = v.get("name")
        rows.append(
            {
                "id": pid,
                "name": str(name).strip() if isinstance(name, str) and name.strip() else pid,
                "system": (v.get("system") or "").strip(),
            }
        )
    return rows


def list_chat_preset_summaries() -> list[dict[str, str]]:
    return [{"id": r["id"], "name": r["name"]} for r in list_chat_presets_for_admin()]


def resolve_chat_system(
    *,
    request_system: str | None,
    request_preset: str | None,
    default_preset_id: str,
    global_system: str,
) -> tuple[str, str | None]:
    """返回 (发给模型的 system 文本, 实际使用的 preset id 或 None)。

    优先级：请求体 system_prompt（非空）> 请求体 preset > 存储/环境默认 preset > FLYAGENT_SYSTEM_PROMPT。
    """
    if request_system is not None and request_system.strip():
        return request_system.strip(), None

    def from_preset(pid: str) -> tuple[str, str | None] | None:
        pid = pid.strip()
        if not pid:
            return None
        text = get_preset_system(pid)
        if not text:
            return None
        return text, pid

    if request_preset is not None and request_preset.strip():
        got = from_preset(request_preset)
        if got is None:
            raise KeyError(request_preset.strip())
        return got

    if default_preset_id.strip():
        got = from_preset(default_preset_id)
        if got is not None:
            return got

    return (global_system or "").strip(), None
