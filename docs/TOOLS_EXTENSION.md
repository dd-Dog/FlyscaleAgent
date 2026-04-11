# FlyAgent 内置工具扩展方案

## 1. 配置文件：`tools_config.yaml`

- 与代码分离，修改 **URL、RSS 源、超时、下游航班接口** 后无需改 Python（改完即生效，依赖进程内 mtime 缓存）。
- 路径默认项目根目录 `tools_config.yaml`，可用环境变量 **`FLYAGENT_TOOLS_CONFIG_PATH`** 指向其它文件。

当前段落：

| 段落 | 作用 |
|------|------|
| `open_meteo` | 天气预报 API；**优先 Nominatim** 将用户输入规范为国家/城市/坐标，失败再回退 Open-Meteo 地理编码 |
| `news_rss` | 综合资讯与关键词搜索的 RSS URL、公共 query 参数 |
| `flight` | 是否启用 `search_flights` 工具；`flight.http` 对接自建航旅 HTTP |
| `tier1_prefetch` | 一级预取规则列表（天气/新闻等），见 §4 |

### 1.1 天气：标准地名（Nominatim）

- **`use_nominatim: true`**（默认）时，`get_weather` 对用户传入的 **整句地名** 发 **单次** OSM [Nominatim](https://nominatim.org/) 搜索，得到 `display_name` 与结构化 `address`（国家、省/州、市等），再拿 **经纬度** 调 Open-Meteo 预报。
- 工具返回中的 **`normalized_place`** 即「国家 + 行政区 + 坐标」组合，模型可直接引用，无需多轮换关键词。
- 须配置合规 **`nominatim_user_agent`**（建议含邮箱），并遵守 [Nominatim 使用政策](https://operations.osmfoundation.org/policies/nominatim/)（访问量高时请自建实例或缓存）。
- **`use_nominatim: false`** 时仅走 Open-Meteo 多策略地理编码（兼容离线/禁用外连场景）。

## 2. 航班工具 `search_flights`

- **模型侧**：识别「北京–和田、明天」等意图并调用工具。
- **服务端**：向 **`flight.http.url`** 发起请求（默认 **POST JSON**）：

```json
{
  "origin_city": "北京",
  "destination_city": "和田",
  "date": "2026-04-11"
}
```

- 日期参数支持 **`YYYY-MM-DD`** 或含 **今天/明天/后天** 的自然语言（服务会先规整为日期字符串再转发）。
- 下游返回 **JSON** 时原样包在 `{"ok":true,"data":...}` 交给模型解读；非 JSON 则截断放入 `raw`。
- 未配置 `url` 时工具返回明确 `error`/`hint`，模型应引导用户走官方 App/网站。
- 可选 **`flight.http.api_key_env`**：从环境变量名读取 token，以 `Authorization: Bearer` 发出。

## 3. 快速增加新工具（导航 / 美食 / 购物等）

推荐按复杂度分三档：

### A. 仅换数据源 URL（零代码或一行）

- 适合：**换 RSS、换 Open-Meteo 兼容端点**。
- 做法：只改 `tools_config.yaml` 对应字段。

### B. 与航班同类：HTTP 下游代理

- 适合：**导航算路、商户列表、电商搜索**等有 HTTP API 的场景。
- 做法：
  1. 在 `tools_config.yaml` 增加段落，例如 `poi_search.http.url`；
  2. 在 `app/builtin_tools.py` 增加 `_xxx_schema()`、`get_builtin_tool_schemas()` 注册、`_call_xxx()` 读配置发请求、`run_builtin_tool` 分支。
- 契约（请求/响应 JSON）写进配置文件注释或本文档，便于前后端对齐。

### C. 复杂逻辑（签名、多步、本地算法）

- 适合：**需要 SDK、缓存、限流、多接口编排**。
- 做法：
  1. 新建 `app/tools_plugins/<name>.py`，暴露 `TOOL_SCHEMA` 与 `async def run(args) -> dict`；
  2. 在启动时或 `get_builtin_tool_schemas()` 中 **import 并注册**（后续可改为扫描包内模块自动注册）。
- 密钥仍放 **`.env`**，配置里只写 **环境变量名**，不写明文。

## 4. 一级规则（Tier1）与 Tool 循环（Tier2）

- **配置位置**：`tools_config.yaml` 顶层 **`tier1_prefetch.rules`**（与 `FLYAGENT_TOOLS_CONFIG_PATH` 指向的同一文件）。可改 **`cues`**、**`anchor`**、**`strip_*`**、**`topic_regex`**、**`days` / `limit_rules`** 等；保存后随文件 mtime 自动重载。
- **省略 `tier1_prefetch` 或未写 `rules` 键**：使用代码内与当前默认 YAML 等价的内置规则。
- **`rules: []`**：显式关闭一级规则匹配（不再回退默认）；与将 **`FLYAGENT_TOOLS_TIER1_ENABLED=false`** 相比，前者仍可走 env 开关，通常二选一即可。
- **新 matcher**：在 `app/tool_tier1.py` 的 **`MATCHERS`** 注册处理函数，并在 YAML 中增加对应 **`matcher`** 条目（仅改 YAML 无法新增全新逻辑类型）。
- **`FLYAGENT_TOOLS_TIER1_ENABLED`**（默认 `true`）：总开关；**命中**时服务端直接 `run_builtin_tool` 再单次 `chat/completions`；**未命中**走 **tools 循环**（`app/llm.py`）。
- 日志：**`path=tier1_prefetch`** / **`path=tool_loop`**；HTTP **`tools`** 字段见 `HTTP_API文档.md`。

## 5. 维护约定

- **密钥**：只进 `.env`，`tools_config.yaml` 可提交仓库；敏感 URL 若需区分环境，用多份 yaml + `FLYAGENT_TOOLS_CONFIG_PATH`。
- **模型可见描述**：在 schema 的 `description` 里写清「何时调用、未配置时的行为」，减少误调用。
- **观测**：Tool 循环日志见 `app.llm.tool_loop` 与 `FLYAGENT_LLM_TOOL_TRACE_PATH`。
