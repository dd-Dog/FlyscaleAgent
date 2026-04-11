"""LLM / Tool 循环专用日志：可写入文件便于排查完整调用链。"""

from __future__ import annotations

import logging
from pathlib import Path

_configured = False

TRACE_LOGGER_NAME = "app.llm.tool_loop"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_log_path(path_str: str) -> Path:
    """相对路径相对项目根目录解析，避免启动时 cwd 不同导致日志写到别处。"""
    p = Path(path_str.strip())
    if p.is_absolute():
        return p
    return _project_root() / p


def ensure_tool_trace_logging() -> None:
    """挂载 FileHandler（若路径非空）。首次调用 `trace_logger()` 时也会自动执行。"""
    global _configured
    if _configured:
        return
    _configured = True

    from app.config import get_app_settings

    s = get_app_settings()
    path = (getattr(s, "llm_tool_trace_path", None) or "").strip()
    log = logging.getLogger(TRACE_LOGGER_NAME)
    log.setLevel(logging.DEBUG)
    if not path:
        return
    p = _resolve_log_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(p, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(fh)
    # 仍向上传播，便于与 uvicorn 控制台级别一致时双写
    log.propagate = True


def trace_logger() -> logging.Logger:
    """获取 tool_loop 日志器；首次调用时会根据配置创建日志文件（无需先启动 uvicorn）。"""
    ensure_tool_trace_logging()
    return logging.getLogger(TRACE_LOGGER_NAME)
