from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings 读 .env 但不会写入 os.environ；models.yaml 里 api_key_env 依赖 os.environ
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

ProviderId = Literal[
    "doubao",
    "deepseek",
    "qwen",
    "kimi",
    "openai",
    "claude",
    "gemini",
]

VALID_PROVIDER_IDS: frozenset[str] = frozenset(get_args(ProviderId))


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLYAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8765
    db_path: str = "./data/flyagent.db"
    default_provider: ProviderId = "qwen"
    # 默认聊天 preset（models.yaml chat_prompts 的 id）；空字符串表示仅用 system_prompt
    default_chat_preset: str = "brief"
    system_prompt: str = ""
    edge_tts_voice: str = "zh-CN-XiaoxiaoNeural"

    # HTTP API: require X-API-Key or Authorization: Bearer (when non-empty)
    api_key: str = ""
    # Admin UI: session login (when username and password are both non-empty)
    admin_user: str = ""
    admin_password: str = ""
    session_secret: str = ""
    # 大模型：base_url / model / api_key_env 等见项目根目录 models.yaml
    models_path: str = "models.yaml"
    # 内置工具 URL 等：tools_config.yaml
    tools_config_path: str = Field(default="tools_config.yaml", validation_alias="FLYAGENT_TOOLS_CONFIG_PATH")

    # 内置天气/新闻工具（OpenAI 兼容 tools）；关闭后仅走普通 chat
    tools_enabled: bool = True
    # 一级规则命中（地名+天气/新闻）时先服务端调工具，再单次 LLM；未命中再走 tool 循环
    tools_tier1_enabled: bool = True
    # 单次用户请求最多调用 chat/completions 次数（含工具后续轮）
    tools_max_model_calls: int = Field(default=6, ge=2, le=24)
    # 上传音频（ASR）最大时长（秒），0 表示不校验
    audio_max_duration_sec: int = Field(default=300, ge=0, le=7200)

    # Tool 循环详细日志文件路径；空字符串表示仅走根日志（不在此模块写文件）
    llm_tool_trace_path: str = Field(
        default="data/llm_tool_trace.log",
        validation_alias="FLYAGENT_LLM_TOOL_TRACE_PATH",
    )


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()


class NlsSettings(BaseSettings):
    """阿里云智能语音交互（NLS），与官方 Python SDK 配套。文档与仓库：https://github.com/aliyun/alibabacloud-nls-python-sdk"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    access_key_id: str = Field(default="", validation_alias="NLS_ACCESS_KEY_ID")
    access_key_secret: str = Field(default="", validation_alias="NLS_ACCESS_KEY_SECRET")
    app_key: str = Field(default="", validation_alias="NLS_APP_KEY")
    gateway_url: str = Field(
        default="wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1",
        validation_alias="NLS_GATEWAY_URL",
    )
    token_region: str = Field(default="cn-shanghai", validation_alias="NLS_TOKEN_REGION")
    # CreateToken 的 Meta 域名，见 https://help.aliyun.com/zh/isi/getting-started/obtain-an-access-token
    token_meta_domain: str = Field(
        default="nls-meta.cn-shanghai.aliyuncs.com",
        validation_alias="NLS_TOKEN_META_DOMAIN",
    )
    token_api_version: str = Field(default="2019-02-28", validation_alias="NLS_TOKEN_API_VERSION")
    # 在阿里云返回的 ExpireTime 之前提前多少秒换新 token（默认 5 分钟）
    token_refresh_margin_sec: int = Field(default=300, ge=60, le=3600, validation_alias="NLS_TOKEN_REFRESH_MARGIN_SEC")
    flash_url: str = Field(
        default="https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/FlashRecognizer",
        validation_alias="NLS_FLASH_URL",
    )
    # Online TTS via NLS SpeechSynthesizer
    tts_voice: str = Field(default="xiaoyun", validation_alias="NLS_TTS_VOICE")
    tts_format: str = Field(default="mp3", validation_alias="NLS_TTS_FORMAT")
    tts_sample_rate: int = Field(default=16000, validation_alias="NLS_TTS_SAMPLE_RATE")
    tts_volume: int = Field(default=50, validation_alias="NLS_TTS_VOLUME")
    tts_speech_rate: int = Field(default=0, validation_alias="NLS_TTS_SPEECH_RATE")
    tts_pitch_rate: int = Field(default=0, validation_alias="NLS_TTS_PITCH_RATE")


@lru_cache
def get_nls_settings() -> NlsSettings:
    return NlsSettings()


def nls_configured() -> bool:
    n = get_nls_settings()
    return bool(n.access_key_id and n.access_key_secret and n.app_key)
