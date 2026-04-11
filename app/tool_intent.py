"""轻量规则：仅在可能涉及实时天气/新闻时挂上 tools，降低简单闲聊的延迟与费用。"""

from __future__ import annotations

import re

# 简单关键词（非严格分词，避免引入 jieba 依赖）
_TOOL_HINT = re.compile(
    r"天气|气温|下雨|降雨|下雪|台风|雾霾|高温|低温|湿度|风力|预报|穿什么"
    r"|weather|forecast|rain|temperature"
    r"|新闻|资讯|头条|时事|最新消息|今天.*事|国内外"
    r"|news|headlines"
    r"|航班|机票|飞机票|起飞|降落|登机|航线|订票|值机"
    r"|flight|airline|ticket",
    re.IGNORECASE,
)


def should_offer_tools(message: str) -> bool:
    m = (message or "").strip()
    if len(m) < 4:
        return False
    # 偏长问题可能隐含实时需求，仍提供工具
    if len(m) > 240:
        return True
    return bool(_TOOL_HINT.search(m))
