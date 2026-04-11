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
  - `use_tools` (boolean, 可选): 内置天气/新闻工具（OpenAI 兼容 `tools`）。`null` 时由服务端 `FLYAGENT_TOOLS_ENABLED` 与关键词轻判决定是否挂工具；`true`/`false` 为强制开/关。开启且 **`FLYAGENT_TOOLS_TIER1_ENABLED=true`** 时，部分句式会先走一级规则服务端预取工具再单次对话，见返回字段说明。

- **返回示例**
```json
{
  "provider": "qwen",
  "text": "你好，我是 FlyAgent。",
  "latency_ms": 520,
  "preset": "brief",
  "tools": {
    "trace_id": "a1b2c3d4e5f6",
    "tools_offered": false,
    "tool_model_calls": 1,
    "tool_turns_with_calls": 0,
    "tier1_prefetch": null,
    "tool_loop_skipped": false,
    "tier1_tool_latency_ms": null
  },
  "audio_base64": "<base64...>",
  "audio_mime": "audio/mpeg"
}
```

- **说明**
  - 使用 **Claude 原生 Messages API** 的 provider 当前不启用 HTTP tools，行为与原先单次 chat 一致。
  - 工具循环最大请求次数由环境变量 **`FLYAGENT_TOOLS_MAX_MODEL_CALLS`** 限制（默认 6）。
  - **`tools.trace_id`**：与服务器日志、文件 **`FLYAGENT_LLM_TOOL_TRACE_PATH`**（默认 `data/llm_tool_trace.log`）中的 `[trace_id]` 行对应，便于按次排查。将 logger **`app.llm.tool_loop`** 设为 **DEBUG** 可输出 `messages_json` 截断片段。
  - **`tools.tier1_prefetch`**：一级规则命中时为 `"weather"` 或 `"news"`，否则为 `null`。
  - **`tools.tool_loop_skipped`**：为 `true` 表示未走 OpenAI `tools` 多轮（通常为 Tier1 预取 + 单次 chat）。
  - **`tools.tier1_tool_latency_ms`**：Tier1 路径下服务端执行内置工具的耗时（毫秒）；非 Tier1 为 `null`。
  - 工具所访问的外部地址在 **`tools_config.yaml`**（可用 **`FLYAGENT_TOOLS_CONFIG_PATH`** 指定路径），含天气、新闻 RSS、**航班下游 HTTP**；扩展方式见 **`docs/TOOLS_EXTENSION.md`**。

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
    - `use_tools`：可选，语义同 `POST /api/chat` 的 `use_tools`

- **上传时长**
  - 服务端按 `format`/`sample_rate` 估算时长，超过 **`FLYAGENT_AUDIO_MAX_DURATION_SEC`**（默认 300 秒）返回 `400`；`0` 表示不限制。

- **成功响应**
  - Body：音频二进制（如 `audio/mpeg`）
  - Header：
    - `Content-Disposition: attachment; filename="voice_reply.mp3"`
    - `X-ASR-Text-UrlEncoded` / `X-Reply-Text-UrlEncoded`：识别文本与回复文本经 **URL 百分号编码**（UTF-8），客户端需 `URLDecoder.decode(..., UTF_8)` 再使用（避免 HTTP 头非 ASCII 限制）
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
  - 时长上限：同全局 `FLYAGENT_AUDIO_MAX_DURATION_SEC`（默认可解析格式下最长 5 分钟）
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
  - 时长上限：同 `FLYAGENT_AUDIO_MAX_DURATION_SEC`
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

### 4.1 Android Java 示例（Retrofit 2 + OkHttp + Gson）

仓库内已提供**可拷贝进 Android Studio Module 的完整 Java 源文件**：[`examples/android-java/`](examples/android-java/)（见其中 `README.md`）。

以下与 Kotlin + Retrofit 用法等价，便于对照或按需粘贴片段。

**Gradle（`app/build.gradle`）**

```gradle
dependencies {
    implementation "com.squareup.retrofit2:retrofit:2.11.0"
    implementation "com.squareup.retrofit2:converter-gson:2.11.0"
    implementation "com.squareup.okhttp3:okhttp:4.12.0"
    implementation "com.squareup.okhttp3:logging-interceptor:4.12.0"
}
```

**API Key 拦截器**

```java
import java.io.IOException;
import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

public final class ApiKeyInterceptor implements Interceptor {
    private final String apiKey;

    public ApiKeyInterceptor(String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    public Response intercept(Chain chain) throws IOException {
        Request req = chain.request().newBuilder()
                .header("X-API-Key", apiKey)
                .build();
        return chain.proceed(req);
    }
}
```

**请求 / 响应模型（Gson，`@SerializedName` 对应 JSON 字段）**

```java
import com.google.gson.annotations.SerializedName;

public final class ChatRequest {
    @SerializedName("message") public String message;
    @SerializedName("provider") public String provider;
    @SerializedName("preset") public String preset;
    @SerializedName("system_prompt") public String systemPrompt;
    @SerializedName("include_audio") public Boolean includeAudio;

    public ChatRequest(String message) {
        this.message = message;
    }
}

public final class ChatResponse {
    @SerializedName("provider") public String provider;
    @SerializedName("text") public String text;
    @SerializedName("latency_ms") public long latencyMs;
    @SerializedName("preset") public String preset;
    @SerializedName("audio_base64") public String audioBase64;
    @SerializedName("audio_mime") public String audioMime;
}

public final class PresetsResponse {
    public static final class PresetItem {
        @SerializedName("id") public String id;
        @SerializedName("name") public String name;
    }
    @SerializedName("presets") public java.util.List<PresetItem> presets;
}

public final class AsrFlashResponse {
    @SerializedName("text") public String text;
    @SerializedName("latency_ms") public long latencyMs;
}
```

**Retrofit 接口**

```java
import okhttp3.MultipartBody;
import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.Multipart;
import retrofit2.http.POST;
import retrofit2.http.Part;
import retrofit2.http.Query;

public interface FlyAgentApi {

    @POST("/api/chat")
    Call<ChatResponse> chat(@Body ChatRequest body);

    @GET("/api/presets")
    Call<PresetsResponse> presets();

    @Multipart
    @POST("/api/asr/flash")
    Call<AsrFlashResponse> asrFlash(
            @Part MultipartBody.Part file,
            @Query("format") String format,
            @Query("sample_rate") int sampleRate
    );

    /** 一站式语音：响应体为音频二进制，文本在 Header 的 *-UrlEncoded 中 */
    @Multipart
    @POST("/api/voice/chat")
    Call<ResponseBody> voiceChat(
            @Part MultipartBody.Part file,
            @Query("asr_engine") String asrEngine,
            @Query("format") String format,
            @Query("sample_rate") int sampleRate,
            @Query("provider") String provider,
            @Query("preset") String preset,
            @Query("voice") String voice
    );
}
```

**构建 `Retrofit`（普通超时 + 上传用长超时可拆两个 `OkHttpClient`）**

```java
import java.util.concurrent.TimeUnit;
import okhttp3.OkHttpClient;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public final class FlyAgentRetrofit {

    public static FlyAgentApi create(String baseUrl, String apiKey) {
        OkHttpClient client = new OkHttpClient.Builder()
                .addInterceptor(new ApiKeyInterceptor(apiKey))
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(180, TimeUnit.SECONDS)
                .writeTimeout(180, TimeUnit.SECONDS)
                .build();

        return new Retrofit.Builder()
                .baseUrl(baseUrl.endsWith("/") ? baseUrl : baseUrl + "/")
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
                .create(FlyAgentApi.class);
    }
}
```

**调用示例（须在后台线程；下面用伪代码 `runOnBackground` 表示）**

```java
import java.io.File;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import okhttp3.ResponseBody;
import retrofit2.Response;

// 聊天
FlyAgentApi api = FlyAgentRetrofit.create("http://你的服务器:8765", "你的API密钥");
ChatRequest req = new ChatRequest("你好");
req.preset = "brief";
req.includeAudio = false;
Response<ChatResponse> chatResp = api.chat(req).execute();
if (chatResp.isSuccessful() && chatResp.body() != null) {
    String reply = chatResp.body().text;
}

// 上传 WAV 做 Flash 识别
File wav = new File("/path/to/recording.wav");
RequestBody rb = RequestBody.create(wav, MediaType.parse("audio/wav"));
MultipartBody.Part part = MultipartBody.Part.createFormData("file", wav.getName(), rb);
Response<AsrFlashResponse> asrResp = api.asrFlash(part, "wav", 16000).execute();

// 语音对话：取音频字节 + 解码 Header 中文
Response<ResponseBody> voiceResp = api.voiceChat(part, "flash", "wav", 16000, null, "brief", null).execute();
if (voiceResp.isSuccessful() && voiceResp.body() != null) {
    byte[] mp3 = voiceResp.body().bytes();
    String asrEnc = voiceResp.headers().get("X-ASR-Text-UrlEncoded");
    String replyEnc = voiceResp.headers().get("X-Reply-Text-UrlEncoded");
    String asrText = asrEnc != null ? URLDecoder.decode(asrEnc, StandardCharsets.UTF_8) : "";
    String replyText = replyEnc != null ? URLDecoder.decode(replyEnc, StandardCharsets.UTF_8) : "";
}
```

**说明**

- 未配置 `FLYAGENT_API_KEY` 时，不要添加 `ApiKeyInterceptor`（或传空不添加该拦截器）。
- Android 9+ 默认禁止明文 HTTP：若仍用 `http://`，需在 `networkSecurityConfig` 中放行对应域名，或改用 HTTPS。
- 生产环境可用 `enqueue` 代替 `execute`，并在主线程更新 UI。

## 5. 非 HTTP（补充）

- 实时语音识别是 **WebSocket**：`/api/asr/stream`
- 本文聚焦 HTTP 接口，WebSocket 协议可另出一份文档。
