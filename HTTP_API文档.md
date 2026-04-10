# FlyAgent HTTP API 文档（Android 调用）

本文档整理当前可通过 HTTP 访问的接口，供 Android 端对接。

## 1. 基础信息

- **Base URL（本地示例）**：`http://127.0.0.1:8765`
- **编码**：`UTF-8`
- **返回**：默认 `application/json`
- **鉴权**：
  - 若 `.env` 配置了 `FLYAGENT_API_KEY`，客户端必须传其一：
    - Header: `X-API-Key: <key>`
    - Header: `Authorization: Bearer <key>`
  - 管理接口（`/api/admin/*`）在开启管理登录后需要 Session Cookie（先调用登录接口）

## 2. 面向客户端的业务接口

## `POST /api/chat`

调用大模型聊天，可选附带 TTS 音频（`audio_base64`）。

- **请求体（JSON）**
  - `message` (string, 必填, 1~16000)
  - `provider` (string, 可选): `doubao | deepseek | qwen | kimi | openai | claude | gemini`
  - `preset` (string, 可选): 对应 `models.yaml` 中 `chat_prompts` 的 id
  - `system_prompt` (string, 可选): 若非空，优先级高于 `preset`
  - `include_audio` (boolean, 可选, 默认 `true`)

- **返回示例**
```json
{
  "provider": "qwen",
  "text": "你好，我是 FlyAgent。",
  "latency_ms": 520,
  "preset": "brief",
  "audio_base64": "<base64...>",
  "audio_mime": "audio/mpeg"
}
```

- **错误**
  - `400`：如 `preset` 无效
  - `401`：缺少/错误 API Key
  - `502`：模型侧错误

---

## `GET /api/presets`

获取聊天预设列表（不返回 system 全文）。

- **返回示例**
```json
{
  "presets": [
    { "id": "brief", "name": "一句话回复" },
    { "id": "detailed", "name": "详细说明" }
  ]
}
```

---

## `POST /api/tts`

阿里云在线语音合成（NLS SpeechSynthesizer）：输入文本，返回语音（Base64）。

- **请求体（JSON）**
  - `text` (string, 必填, 1~5000)
  - `voice` (string, 可选): 发音人，如 `xiaoyun`（不传则用服务端配置）

- **返回示例**
```json
{
  "audio_base64": "<base64...>",
  "audio_mime": "audio/mpeg",
  "latency_ms": 420
}
```

- **错误**
  - `401`：缺少/错误 API Key
  - `502`：阿里云语音合成失败（参数错误、鉴权错误、网关错误等）

---

## `POST /api/voice/chat`

一站式语音对话（低端安卓推荐）：

1. 上传音频文件  
2. 服务端先做 ASR  
3. 再调用大模型（默认 `brief` 单句回复）  
4. 最后做 TTS  
5. **直接返回可播放音频文件**（二进制响应）

- **请求**
  - `Content-Type: multipart/form-data`
  - Form 字段：`file`
  - Query 参数：
    - `asr_engine`：`flash | recognize`，默认 `flash`
    - `format`：默认 `wav`
    - `sample_rate`：默认 `16000`
    - `provider`：可选，模型提供商；不传走默认
    - `preset`：可选；不传时默认 `brief`
    - `voice`：可选；不传走 `NLS_TTS_VOICE`

- **成功响应**
  - Body：音频二进制（如 `audio/mpeg`）
  - Header：
    - `Content-Disposition: attachment; filename="voice_reply.mp3"`
    - `X-ASR-Text`: 识别文本
    - `X-Reply-Text`: 大模型回复文本
    - `X-Provider`: 实际模型
    - `X-Preset`: 实际预设
    - `X-Total-Latency-Ms`: 全链路耗时

- **错误**
  - `400`：参数错误
  - `401`：缺少/错误 API Key
  - `413`：文件过大（>100MB）
  - `422`：ASR 未识别到文本
  - `502`：ASR/LLM/TTS 任一阶段失败

---

## `GET /api/asr/ready`

检查语音识别环境状态（阿里云 NLS）。

- **返回示例**
```json
{
  "nls_configured": true,
  "sdk_installed": true
}
```

---

## `POST /api/asr/recognize`

语音文件快速识别（SDK 一句话识别路径）。

- **请求**
  - `Content-Type: multipart/form-data`
  - Form 字段：`file`（音频文件）
  - Query 参数：
    - `format` (string, 默认 `pcm`)：如 `pcm/wav/mp3`
    - `sample_rate` (int, 默认 `16000`, 范围 `8000~48000`)

- **返回示例**
```json
{
  "text": "识别文本",
  "format": "wav",
  "sample_rate": 16000
}
```

- **限制与错误**
  - 文件大小上限：`32MB`
  - `413`：文件过大
  - `503`：NLS 未配置
  - `502`：识别失败

---

## `POST /api/asr/flash`

语音文件极速识别（服务端直连阿里云 FlashRecognizer HTTP）。

- **请求**
  - `Content-Type: multipart/form-data`
  - Form 字段：`file`
  - Query 参数：
    - `format` (string, 默认 `wav`)
    - `sample_rate` (int, 默认 `16000`, 范围 `8000~48000`)

- **返回示例**
```json
{
  "text": "识别文本",
  "format": "wav",
  "sample_rate": 16000,
  "latency_ms": 880,
  "task_id": "xxxxxxxx",
  "http_status": 200
}
```

- **限制与错误**
  - 文件大小上限：`100MB`
  - `413`：文件过大
  - `503`：NLS 未配置
  - `502`：FlashRecognizer 调用失败

## 3. 管理端 HTTP 接口

以下接口主要给管理页面用，Android 一般仅在有后台管理需求时调用。

## `GET /api/admin/session`

- 返回是否开启管理登录、当前会话是否已登录。

## `POST /api/admin/login`

- 请求体：
```json
{ "username": "admin", "password": "123456" }
```
- 登录成功后，服务端通过 Cookie 维持会话。

## `POST /api/admin/logout`

- 清除当前会话。

## `GET /api/admin/summary`

- 返回默认模型、默认聊天 preset、访问统计。

## `GET /api/admin/recent?limit=50`

- 返回最近访问记录（最大 200）。

## `POST /api/admin/default_provider`

- 请求体：
```json
{ "default_provider": "qwen" }
```

## `GET /api/admin/prompts`

- 返回预设详情（含 system 全文）。

## `POST /api/admin/default_chat_preset`

- 请求体：
```json
{ "preset": "brief" }
```
- 传空字符串 `""` 表示取消默认 preset。

## 4. Android 调用建议

- **统一网络层**
  - JSON 接口：`application/json`
  - 上传接口（ASR）：`multipart/form-data`
- **鉴权**
  - 若开启 `FLYAGENT_API_KEY`，统一在拦截器加 `X-API-Key`
- **超时**
  - ASR 接口建议设置更长超时（例如 60~180 秒）
- **大响应处理**
  - `/api/chat` 若 `include_audio=true` 可能返回较大 `audio_base64`，可按场景关闭

## 5. 非 HTTP（补充）

- 实时语音识别是 **WebSocket**：`/api/asr/stream`
- 本文聚焦 HTTP 接口，WebSocket 协议可另出一份文档。
