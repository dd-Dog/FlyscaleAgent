"""加载项目根目录 tools_config.yaml（mtime 变化自动失效缓存）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_app_settings


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def tools_config_file_path() -> Path:
    raw = (get_app_settings().tools_config_path or "tools_config.yaml").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = _project_root() / p
    return p


@lru_cache(maxsize=8)
def _load_document(path_str: str, mtime: float) -> dict[str, Any]:
    with open(path_str, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def get_tools_config() -> dict[str, Any]:
    path = tools_config_file_path()
    if not path.is_file():
        return {}
    return _load_document(str(path.resolve()), path.stat().st_mtime)


def tool_loop_system_suffix_override() -> str | None:
    """
    tool_loop.system_suffix 显式配置时返回该字符串（可为空串表示不追加工具说明）；
    未配置该项则返回 None，由 llm 模块使用内置默认后缀。
    """
    cfg = get_tools_config()
    block = cfg.get("tool_loop")
    if not isinstance(block, dict) or "system_suffix" not in block:
        return None
    val = block["system_suffix"]
    if isinstance(val, str):
        return val
    return None
