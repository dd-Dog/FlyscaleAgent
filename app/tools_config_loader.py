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
