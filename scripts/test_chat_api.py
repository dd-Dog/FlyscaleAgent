#!/usr/bin/env python3
"""
调用 FlyAgent POST /api/chat，便于本地或联调自测。

用法（在项目根目录）:
  python scripts/test_chat_api.py
  python scripts/test_chat_api.py -m "查询明天石家庄的天气" --use-tools true
  python scripts/test_chat_api.py --base-url http://127.0.0.1:8765 --api-key YOUR_KEY

若服务端配置了 FLYAGENT_API_KEY，请传 --api-key 或导出同名环境变量。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        load_dotenv(root / ".env")
    except ImportError:
        pass


def _summarize_response(data: dict[str, Any]) -> dict[str, Any]:
    """打印用：去掉或缩短 audio_base64。"""
    out = dict(data)
    if "audio_base64" in out and isinstance(out["audio_base64"], str):
        raw = out["audio_base64"]
        out["audio_base64"] = f"<{len(raw)} chars base64>"
    return out


def main() -> int:
    _load_dotenv()

    p = argparse.ArgumentParser(description="测试 POST /api/chat")
    p.add_argument(
        "--base-url",
        default=os.environ.get("FLYAGENT_CHAT_BASE_URL", "http://59.110.55.96:8765"),
        help="服务根地址，默认 http://59.110.55.96:8765 或环境变量 FLYAGENT_CHAT_BASE_URL",
    )
    p.add_argument(
        "-m",
        "--message",
        default="你好，用一句话自我介绍。",
        help="用户消息",
    )
    p.add_argument("--provider", default=None, help="doubao|deepseek|qwen|kimi|openai|claude|gemini")
    p.add_argument("--preset", default=None, help="models.yaml chat_prompts 的 id，如 brief")
    p.add_argument(
        "--use-tools",
        choices=("true", "false", "none"),
        default="none",
        help="是否强制挂内置工具：true/false；none=由服务端关键词与配置决定（默认）",
    )
    p.add_argument(
        "--no-audio",
        action="store_true",
        help="请求体 include_audio=false，减少响应体积、加快请求",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("FLYAGENT_API_KEY", "").strip() or None,
        help="X-API-Key；默认读环境变量 FLYAGENT_API_KEY",
    )
    p.add_argument("--timeout", type=float, default=180.0, help="HTTP 超时秒数")
    args = p.parse_args()

    url = args.base_url.rstrip("/") + "/api/chat"
    body: dict[str, Any] = {"message": args.message, "include_audio": not args.no_audio}
    if args.provider:
        body["provider"] = args.provider
    if args.preset is not None:
        body["preset"] = args.preset
    if args.use_tools == "true":
        body["use_tools"] = True
    elif args.use_tools == "false":
        body["use_tools"] = False

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    print("POST", url, flush=True)
    print("body:", json.dumps(body, ensure_ascii=False), flush=True)

    try:
        r = httpx.post(url, json=body, headers=headers, timeout=args.timeout)
    except httpx.RequestError as e:
        print("请求失败:", e, file=sys.stderr)
        return 1

    print("status:", r.status_code, flush=True)
    try:
        data = r.json()
    except json.JSONDecodeError:
        print(r.text[:2000])
        return 1 if r.status_code >= 400 else 0

    if r.status_code >= 400:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 1

    summary = _summarize_response(data)
    text = data.get("text") or ""
    print("--- text ---")
    print(text[:8000] + ("…" if len(text) > 8000 else ""))
    print("--- json (audio 已缩写) ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
