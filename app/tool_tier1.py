"""
一级轻量意图 + 参数抽取：规则主要来自 tools_config.yaml 的 tier1_prefetch.rules。
命中则服务端直接调内置工具，再由 LLM 单次润色；未命中交给二级 tool 循环。

扩展方式：
- 改关键词/正则：只改 YAML（文件 mtime 变化后自动重载）。
- 新 matcher 类型：在 MATCHERS 注册处理函数，并在 YAML 中写 matcher 名。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.tools_config_loader import get_tools_config

logger = logging.getLogger(__name__)


@dataclass
class Tier1Decision:
    """prefetch=True 时表示应走「先工具、后单次 LLM」快捷路径。"""

    prefetch: bool = False
    kind: str = ""
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for k, v in over.items():
        if v is None:
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# 与 tools_config.yaml 中 tier1_prefetch.rules 结构一致；YAML 缺省段时使用
_RULE_TEMPLATES: dict[str, dict[str, Any]] = {
    "weather_place": {
        "matcher": "weather_place",
        "kind": "weather",
        "tool": "get_weather",
        "anchor": "天气",
        "cues": ["天气", "气温", "下雨", "降雨", "下雪", "预报"],
        "strip_leading": r"^[\s，。！？、；请问帮我查一下我想知道:]+",
        "strip_remove": [
            r"(查询|查一下|查下|查查看|看下|看看|告诉我|说下|麻烦|请)",
            r"(明天|今日|今天|后天|明日|今儿|明儿|後天)",
        ],
        "place_strip_chars": " 的、，。！？",
        "collapse_ws": True,
        "place_len_min": 2,
        "place_len_max": 36,
        "days": {
            "default": 1,
            "clamp": [1, 3],
            "rules": [
                {"if_contains": ["后天", "後天"], "value": 3},
                {"if_contains": ["明天", "明日", "明儿"], "value": 2},
            ],
        },
    },
    "news_headlines": {
        "matcher": "news_headlines",
        "kind": "news",
        "tool": "get_news_headlines",
        "max_input_len": 400,
        "cues": ["新闻", "头条", "资讯", "消息"],
        "topic_regex": (
            r"(?:关于|有关|聊聊|说说)\s*([^\s，。！？]{1,24}?)\s*(?:的)?\s*(?:新闻|消息|资讯|头条)"
        ),
        "topic_min_len": 2,
        "limit_default": 8,
        "limit_rules": [{"if_contains": ["5", "五条"], "value": 5}],
    },
}


def _days_from_rule(rule: dict[str, Any], text: str) -> int:
    block = rule.get("days") or {}
    default = int(block.get("default", 1))
    clamp = block.get("clamp") or [1, 3]
    lo, hi = int(clamp[0]), int(clamp[1])
    rules = block.get("rules") or []
    for item in rules:
        if not isinstance(item, dict):
            continue
        subs = item.get("if_contains") or []
        if any(s in text for s in subs):
            return max(lo, min(hi, int(item.get("value", default))))
    return max(lo, min(hi, default))


def _extract_place_before_anchor(rule: dict[str, Any], text: str) -> str | None:
    anchor = str(rule.get("anchor") or "天气")
    if anchor not in text:
        return None
    idx = text.index(anchor)
    before = text[:idx]
    # 先整词/短语 strip_remove，再 strip_leading，避免 [] 误拆「查询」等（单字「查」在 leading 类里会先被吃掉）
    for pat in rule.get("strip_remove") or []:
        if isinstance(pat, str) and pat:
            before = re.sub(pat, "", before)
    sl = rule.get("strip_leading")
    if isinstance(sl, str) and sl:
        before = re.sub(sl, "", before)
    chars = str(rule.get("place_strip_chars") or "")
    before = before.strip(chars)
    if rule.get("collapse_ws", True):
        before = re.sub(r"\s+", "", before)
    lo = int(rule.get("place_len_min", 2))
    hi = int(rule.get("place_len_max", 36))
    if lo <= len(before) <= hi:
        return before
    return None


def _match_weather_place(rule: dict[str, Any], text: str) -> dict[str, Any] | None:
    cues = rule.get("cues") or []
    if not isinstance(cues, list) or not any(isinstance(c, str) and c in text for c in cues):
        return None
    city = _extract_place_before_anchor(rule, text)
    if not city:
        return None
    return {"city": city, "days": _days_from_rule(rule, text)}


def _match_news_headlines(rule: dict[str, Any], text: str) -> dict[str, Any] | None:
    max_len = int(rule.get("max_input_len", 400))
    if len(text) > max_len:
        return None
    cues = rule.get("cues") or []
    if not isinstance(cues, list) or not any(isinstance(c, str) and c in text for c in cues):
        return None
    topic: str | None = None
    tr = rule.get("topic_regex")
    if isinstance(tr, str) and tr.strip():
        m = re.search(tr, text)
        if m:
            topic = m.group(1).strip()
    tmin = int(rule.get("topic_min_len", 2))
    if topic is not None and len(topic) < tmin:
        topic = None
    lim = int(rule.get("limit_default", 8))
    for item in rule.get("limit_rules") or []:
        if not isinstance(item, dict):
            continue
        subs = item.get("if_contains") or []
        if any(s in text for s in subs):
            lim = int(item.get("value", lim))
            break
    return {"topic": topic, "limit": lim}


MATCHERS: dict[str, Callable[[dict[str, Any], str], dict[str, Any] | None]] = {
    "weather_place": _match_weather_place,
    "news_headlines": _match_news_headlines,
}


def _normalize_rule(raw: dict[str, Any]) -> dict[str, Any] | None:
    m = raw.get("matcher")
    if not isinstance(m, str) or m not in _RULE_TEMPLATES:
        logger.warning("tier1_prefetch: 跳过未知 matcher: %r", m)
        return None
    return _deep_merge(_RULE_TEMPLATES[m], raw)


def _default_rules_list() -> list[dict[str, Any]]:
    return [
        _deep_merge(_RULE_TEMPLATES["weather_place"], {}),
        _deep_merge(_RULE_TEMPLATES["news_headlines"], {}),
    ]


def _load_resolved_rules() -> list[dict[str, Any]]:
    cfg = get_tools_config()
    block = cfg.get("tier1_prefetch")
    if not isinstance(block, dict):
        return _default_rules_list()
    if "rules" not in block:
        return _default_rules_list()

    r = block.get("rules")
    if not isinstance(r, list):
        return _default_rules_list()
    # 显式 rules: [] 表示关闭一级规则（不再回退默认）
    if len(r) == 0:
        return []

    raw_rules: list[Any] = r

    out: list[dict[str, Any]] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        merged = _normalize_rule(item)
        if merged:
            out.append(merged)
    if not out:
        logger.warning("tier1_prefetch.rules 无有效条目，使用内置默认")
        return _default_rules_list()
    return out


def analyze_tier1(user_text: str) -> Tier1Decision:
    t = (user_text or "").strip()
    if not t:
        return Tier1Decision()

    for rule in _load_resolved_rules():
        name = rule.get("matcher")
        if not isinstance(name, str):
            continue
        fn = MATCHERS.get(name)
        if not fn:
            logger.warning("tier1_prefetch: 未注册 matcher 处理函数: %s", name)
            continue
        args = fn(rule, t)
        if args:
            tool = str(rule.get("tool") or "")
            kind = str(rule.get("kind") or "")
            if not tool or not kind:
                continue
            return Tier1Decision(
                prefetch=True,
                kind=kind,
                tool_name=tool,
                args=args,
            )

    return Tier1Decision()
