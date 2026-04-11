"""内置工具：天气、新闻、航班（地址从 tools_config.yaml 读取）。"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.tools_config_loader import get_tools_config

logger = logging.getLogger(__name__)

# 地理编码：先截断常见行政区划后缀，再尝试英文（Open-Meteo 对纯中文有时需 language=zh）
_GEO_SUFFIXES: tuple[str, ...] = (
    "滨海新区",
    "新区",
    "经济技术开发区",
    "高新区",
    "自贸试验区",
    "市辖区",
    "自治州",
    "自治区",
    "地区",
    "市",
    "区",
    "县",
    "州",
)

_BUILTIN_ROMANIZE: dict[str, str] = {
    "天津": "Tianjin",
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "西安": "Xi'an",
    "南京": "Nanjing",
    "武汉": "Wuhan",
    "重庆": "Chongqing",
    "苏州": "Suzhou",
    "和田": "Hotan",
    "乌鲁木齐": "Urumqi",
    "青岛": "Qingdao",
    "大连": "Dalian",
    "厦门": "Xiamen",
    "宁波": "Ningbo",
    "无锡": "Wuxi",
    "长沙": "Changsha",
    "郑州": "Zhengzhou",
    "沈阳": "Shenyang",
    "哈尔滨": "Harbin",
    "昆明": "Kunming",
    "济南": "Jinan",
}


def _city_name_variants(city: str) -> list[str]:
    c = (city or "").strip()
    seen: set[str] = set()
    out: list[str] = []

    def add(x: str) -> None:
        x = x.strip()
        if not x or x in seen:
            return
        seen.add(x)
        out.append(x)

    add(c)
    om = _om_cfg()
    aliases = om.get("geocode_aliases")
    if isinstance(aliases, dict) and c in aliases:
        add(str(aliases[c]))

    for suf in _GEO_SUFFIXES:
        if len(c) > len(suf) + 1 and c.endswith(suf):
            add(c[: -len(suf)])

    return out


async def _geocode_open_meteo(
    client: httpx.AsyncClient,
    geo_url: str,
    city: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    tried: list[str] = []
    variants = _city_name_variants(city)
    om = _om_cfg()
    raw_langs = om.get("geocode_language_try")
    if isinstance(raw_langs, list) and raw_langs:
        langs = [str(x).strip() for x in raw_langs if str(x).strip()]
    else:
        langs = ["zh", "en"]

    for v in variants:
        for lang in langs:
            label = f"{v}|lang={lang}"
            tried.append(label)
            r = await client.get(
                geo_url,
                params={"name": v, "count": 10, "language": lang},
            )
            r.raise_for_status()
            geo = r.json()
            results = geo.get("results") if isinstance(geo, dict) else None
            if not results:
                continue
            cn = [x for x in results if str(x.get("country_code") or "").upper() == "CN"]
            loc = cn[0] if cn else results[0]
            return loc, tried

    for v in variants:
        en = _BUILTIN_ROMANIZE.get(v)
        if not en:
            continue
        label = f"{en}|lang=en(←{v})"
        tried.append(label)
        r = await client.get(
            geo_url,
            params={"name": en, "count": 8, "language": "en"},
        )
        r.raise_for_status()
        geo = r.json()
        results = geo.get("results") if isinstance(geo, dict) else None
        if not results:
            continue
        cn = [x for x in results if str(x.get("country_code") or "").upper() == "CN"]
        loc = cn[0] if cn else results[0]
        return loc, tried

    return None, tried


def _weather_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "查询指定城市当前天气与短期预报（实时公开数据）。"
                "可传入用户原话中的地名（含省市区县）；服务端会先规范为标准国家/城市/坐标再查预报。"
                "仅当用户明确需要天气、气温、降雨等信息时调用；每个用户问题最多调用一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市中文或英文名称（如 上海、滨海新区可写全称；服务端会自动尝试去后缀与英文兜底）",
                    },
                    "days": {
                        "type": "integer",
                        "description": "预报天数，1~3",
                        "default": 1,
                    },
                },
                "required": ["city"],
            },
        },
    }


def _news_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_news_headlines",
            "description": (
                "获取近期新闻标题摘要（RSS，源地址见 tools_config.yaml）。"
                "仅当用户询问新闻、头条、时事动态时使用；可带关键词缩小范围。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "可选关键词，如 科技、体育；留空则综合资讯",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，1~12",
                        "default": 8,
                    },
                },
                "required": [],
            },
        },
    }


def _flight_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": (
                "查询两座城市之间、指定日期的航班/机票相关实时信息。"
                "当用户问航班、机票、班次、起飞到达时间等行程问题时调用。"
                "若服务端未配置下游 HTTP 接口，将返回配置说明，请如实转告用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin_city": {
                        "type": "string",
                        "description": "出发城市中文名，如 北京",
                    },
                    "destination_city": {
                        "type": "string",
                        "description": "到达城市中文名，如 和田",
                    },
                    "date": {
                        "type": "string",
                        "description": '出发日期：YYYY-MM-DD，或含「今天」「明天」的自然语言',
                    },
                },
                "required": ["origin_city", "destination_city", "date"],
            },
        },
    }


def get_builtin_tool_schemas() -> list[dict[str, Any]]:
    """供 LLM 的 tools 列表；航班工具可按 tools_config.yaml flight.enabled 关闭。"""
    cfg = get_tools_config()
    flight_cfg = cfg.get("flight") if isinstance(cfg.get("flight"), dict) else {}
    enabled = flight_cfg.get("enabled", True)
    out = [_weather_schema(), _news_schema()]
    if enabled is not False:
        out.append(_flight_schema())
    return out


def _strip_xml_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _om_cfg() -> dict[str, Any]:
    cfg = get_tools_config()
    raw = cfg.get("open_meteo")
    return raw if isinstance(raw, dict) else {}


def _news_cfg() -> dict[str, Any]:
    cfg = get_tools_config()
    raw = cfg.get("news_rss")
    return raw if isinstance(raw, dict) else {}


def _normalize_travel_date(text: str) -> str:
    t = (text or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    now = datetime.now().date()
    if "明天" in t or t == "明天":
        return (now + timedelta(days=1)).isoformat()
    if "今天" in t or t == "今天":
        return now.isoformat()
    if "后天" in t or t == "后天":
        return (now + timedelta(days=2)).isoformat()
    return t


def _nominatim_pick_best(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    if not items:
        return None

    def score(it: dict[str, Any]) -> tuple[int, float]:
        addr = it.get("address") or {}
        cc = str(addr.get("country_code") or "").lower()
        # 中文查询略偏好中国结果
        pref_cn = 1 if re.search(r"[\u4e00-\u9fff]", query) else 0
        cn_bonus = 2 if cc == "cn" and pref_cn else (1 if cc == "cn" else 0)
        imp = float(it.get("importance") or 0.0)
        return (cn_bonus, imp)

    return max(items, key=lambda it: score(it))


async def _nominatim_resolve(
    client: httpx.AsyncClient,
    query: str,
    om: dict[str, Any],
) -> dict[str, Any] | None:
    """
    OpenStreetMap Nominatim：单次把用户输入解析为标准 display_name + address + 坐标。
    需合法 User-Agent（见 tools_config / OSM 政策）。
    """
    if om.get("use_nominatim") is False:
        return None
    base = (om.get("nominatim_url") or "https://nominatim.openstreetmap.org/search").strip()
    ua = (om.get("nominatim_user_agent") or "").strip()
    if not ua:
        ua = "FlyAgent/1.0 (+https://github.com/dd-Dog/FlyscaleAgent)"
    try:
        limit = max(1, min(10, int(om.get("nominatim_limit") or 5)))
    except (TypeError, ValueError):
        limit = 5

    params: dict[str, Any] = {
        "q": query.strip(),
        "format": "jsonv2",
        "limit": limit,
        "addressdetails": 1,
    }
    cc_raw = om.get("nominatim_countrycodes")
    if cc_raw is not None and str(cc_raw).strip():
        params["countrycodes"] = str(cc_raw).strip().lower()

    headers = {
        "User-Agent": ua,
        "Accept-Language": (om.get("nominatim_accept_language") or "zh-CN,zh;q=0.9,en;q=0.8"),
    }

    try:
        r = await client.get(base, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError, TypeError) as e:
        logger.warning("nominatim request failed: %s", e)
        return None

    if not isinstance(data, list) or not data:
        return None

    best = _nominatim_pick_best(data, query)
    if not best:
        return None
    try:
        lat = float(best["lat"])
        lon = float(best["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    addr = best.get("address") if isinstance(best.get("address"), dict) else {}
    disp = (best.get("display_name") or query).strip()
    country = str(addr.get("country") or "")
    short_name = (
        addr.get("city")
        or addr.get("town")
        or addr.get("county")
        or addr.get("state")
        or addr.get("suburb")
        or (disp.split(",")[0].strip() if disp else query)
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "name": str(short_name).strip() or query,
        "country": country,
        "display_name": disp,
        "address": addr,
        "geocoder": "nominatim",
    }


async def _get_weather(city: str, days: int) -> dict[str, Any]:
    days = max(1, min(3, int(days or 1)))
    city = (city or "").strip()
    if not city:
        return {"error": "city 不能为空"}

    om = _om_cfg()
    geo_url = (om.get("geocode_url") or "https://geocoding-api.open-meteo.com/v1/search").strip()
    fc_url = (om.get("forecast_url") or "https://api.open-meteo.com/v1/forecast").strip()
    tz = (om.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"

    async with httpx.AsyncClient(timeout=25.0) as client:
        loc: dict[str, Any] | None = await _nominatim_resolve(client, city, om)
        geocoder = "nominatim"
        tried: list[str] = []

        if loc is None:
            geocoder = "open-meteo"
            loc2, tried = await _geocode_open_meteo(client, geo_url, city)
            loc = loc2
            if loc is None:
                return {
                    "error": f"未找到城市: {city}",
                    "hint": "可检查网络、tools_config.open_meteo.use_nominatim / nominatim_user_agent，或 geocode_aliases",
                    "geocode_attempts": tried[:24],
                }

        lat, lon = loc.get("latitude"), loc.get("longitude")
        name = loc.get("name")
        country = loc.get("country")
        if lat is None or lon is None:
            return {
                "error": "地理编码结果无效",
                "geocoder": geocoder,
                "geocode_attempts": tried[:24] if geocoder == "open-meteo" else [],
            }

        fc_r = await client.get(
            fc_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": tz,
                "forecast_days": days,
            },
        )
        fc_r.raise_for_status()
        fc = fc_r.json()

    normalized: dict[str, Any] | None = None
    if loc.get("geocoder") == "nominatim" and isinstance(loc.get("address"), dict):
        addr = loc["address"]
        normalized = {
            "input": city,
            "display_name": loc.get("display_name"),
            "country": addr.get("country"),
            "country_code": addr.get("country_code"),
            "state": addr.get("state"),
            "city": addr.get("city"),
            "county": addr.get("county"),
            "town": addr.get("town"),
            "latitude": lat,
            "longitude": lon,
        }

    out: dict[str, Any] = {
        "location": {
            "name": name,
            "country": country,
            "latitude": lat,
            "longitude": lon,
        },
        "current": fc.get("current"),
        "daily": fc.get("daily"),
        "source": "open-meteo",
        "geocoding": geocoder,
    }
    if normalized is not None:
        out["normalized_place"] = normalized
    if geocoder == "open-meteo" and tried:
        out["geocode_attempts"] = tried[:24]

    return out


async def _get_news_headlines(topic: str | None, limit: int) -> dict[str, Any]:
    limit = max(1, min(12, int(limit or 8)))
    topic = (topic or "").strip()
    nc = _news_cfg()
    base_default = (nc.get("default_url") or "https://news.google.com/rss").strip()
    base_search = (nc.get("search_url") or "https://news.google.com/rss/search").strip()
    qp = nc.get("query_params")
    base_params: dict[str, str] = {}
    if isinstance(qp, dict):
        for k, v in qp.items():
            if v is not None:
                base_params[str(k)] = str(v)

    if topic:
        url = base_search
        params = {**base_params, "q": topic}
    else:
        url = base_default
        params = dict(base_params)

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        text = r.text

    titles: list[str] = []
    try:
        root = ET.fromstring(text)
        for el in root.iter():
            tag = _strip_xml_ns(el.tag)
            if tag == "item":
                title_el = None
                for child in el:
                    if _strip_xml_ns(child.tag) == "title":
                        title_el = child
                        break
                if title_el is not None and title_el.text:
                    tt = re.sub(r"<[^>]+>", "", title_el.text).strip()
                    if tt and tt not in titles:
                        titles.append(tt)
            elif tag == "entry":
                title_el = None
                for child in el:
                    if _strip_xml_ns(child.tag) == "title":
                        title_el = child
                        break
                if title_el is not None and title_el.text:
                    tt = re.sub(r"<[^>]+>", "", title_el.text).strip()
                    if tt and tt not in titles:
                        titles.append(tt)
    except ET.ParseError as e:
        logger.warning("RSS parse error: %s", e)
        return {"error": "新闻源解析失败", "raw_len": len(text)}

    host = url.split("/")[2] if "://" in url else url
    return {"headlines": titles[:limit], "count": len(titles[:limit]), "source": host}


async def _search_flights(origin_city: str, destination_city: str, date: str) -> dict[str, Any]:
    cfg = get_tools_config()
    fc = cfg.get("flight")
    if not isinstance(fc, dict) or fc.get("enabled") is False:
        return {"error": "航班工具已在配置中关闭 (flight.enabled: false)"}

    http = fc.get("http")
    if not isinstance(http, dict):
        http = {}

    url = (http.get("url") or "").strip()
    if not url:
        return {
            "error": "未配置航班查询 HTTP 下游",
            "hint": "在 tools_config.yaml 中设置 flight.http.url，指向你的航旅微服务；"
            "建议 POST JSON：origin_city, destination_city, date(YYYY-MM-DD)。",
        }

    method = (http.get("method") or "POST").upper()
    timeout = float(http.get("timeout_sec") or 25)
    headers: dict[str, str] = {}
    extra = http.get("extra_headers")
    if isinstance(extra, dict):
        for k, v in extra.items():
            headers[str(k)] = str(v)

    key_env = (http.get("api_key_env") or "").strip()
    if key_env:
        key = os.environ.get(key_env, "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"

    origin_city = (origin_city or "").strip()
    destination_city = (destination_city or "").strip()
    date_iso = _normalize_travel_date(date)
    payload = {
        "origin_city": origin_city,
        "destination_city": destination_city,
        "date": date_iso,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "GET":
            r = await client.get(url, params=payload, headers=headers)
        else:
            r = await client.post(url, json=payload, headers=headers)

    ct = (r.headers.get("content-type") or "").lower()
    text = r.text
    if r.status_code >= 400:
        return {
            "error": f"下游 HTTP {r.status_code}",
            "body_preview": text[:800],
        }

    if "json" in ct:
        try:
            body = r.json()
            return {"ok": True, "data": body, "source": url}
        except Exception:
            return {"ok": True, "raw": text[:4000], "source": url}

    return {"ok": True, "raw": text[:4000], "source": url}


async def run_builtin_tool(name: str, args: dict[str, Any]) -> str:
    try:
        if name == "get_weather":
            out = await _get_weather(str(args.get("city") or ""), int(args.get("days") or 1))
        elif name == "get_news_headlines":
            topic = args.get("topic")
            out = await _get_news_headlines(
                str(topic).strip() if topic is not None else None,
                int(args.get("limit") or 8),
            )
        elif name == "search_flights":
            out = await _search_flights(
                str(args.get("origin_city") or ""),
                str(args.get("destination_city") or ""),
                str(args.get("date") or ""),
            )
        else:
            out = {"error": f"未知工具: {name}"}
        return json.dumps(out, ensure_ascii=False)
    except httpx.HTTPError as e:
        logger.warning("tool http error %s: %s", name, e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("tool %s failed", name)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
