"""配置加载与模型供应商预设。

只需要在 .env 里写两行就能接入真实模型：

    PROVIDER=zhipu
    API_KEY=xxxx

其余 base_url / model 全部由内置预设提供。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 显式指定 .env 路径，避免从其它工作目录启动时读不到配置
load_dotenv(BASE_DIR / ".env")

# 内置供应商预设：base_url 与默认模型写死在这里，用户无需手填
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "zhipu": {
        "label": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "embedding_model": "embedding-3",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "note": "glm-4-flash 提供免费额度，适合先跑通",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "embedding_model": "",
        "key_url": "https://platform.deepseek.com/api_keys",
        "note": "按 token 计费，需要账户余额；官方暂未提供 embedding 接口，检索自动走 BM25",
    },
    "dashscope": {
        "label": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "embedding_model": "text-embedding-v3",
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "note": "通义千问 qwen-plus，OpenAI 兼容模式",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容接口",
        "base_url": "",
        "model": "",
        "embedding_model": "",
        "key_url": "",
        "note": "需要在 .env 里补充 OPENAI_BASE_URL 与 MODEL_NAME",
    },
}

# 各供应商专属 Key 环境变量，作为 API_KEY 的兜底
PROVIDER_KEY_ENV = {
    "zhipu": "ZHIPU_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
}


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    provider: str
    provider_label: str
    base_url: str
    model: str
    embedding_model: str
    api_key: str
    temperature: float
    max_tool_rounds: int
    request_timeout: float
    host: str
    port: int
    knowledge_dir: Path
    log_dir: Path
    data_dir: Path
    tool_backend: str
    tool_api_base: str
    tool_api_key: str
    tool_api_key_header: str

    @property
    def mode(self) -> str:
        """live = 真实模型；demo = 本地规则引擎。"""
        return "live" if self.api_key and self.base_url and self.model else "demo"

    @property
    def mode_label(self) -> str:
        return "真实模型" if self.mode == "live" else "演示模式"

    @property
    def can_embed(self) -> bool:
        """只有真实模式且有 embedding 模型时才启用向量检索。"""
        return bool(self.api_key and self.base_url and self.embedding_model and self.mode == "live")

    def public_info(self) -> dict:
        return {
            "mode": self.mode,
            "mode_label": self.mode_label,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "model": self.model if self.mode == "live" else "local-rules",
            "base_url": self.base_url,
            "embedding_model": self.embedding_model if self.can_embed else None,
            "tool_backend": self.tool_backend,
        }


def load_settings() -> Settings:
    provider = _env("PROVIDER", "zhipu").lower()
    if provider not in PROVIDER_PRESETS:
        provider = "custom"

    preset = PROVIDER_PRESETS[provider]
    base_url = preset["base_url"]
    model = preset["model"]

    # custom（或预设缺省时）允许用 OPENAI_BASE_URL / MODEL_NAME 覆盖，
    # 这是 .env 里唯一需要手填 base_url 的场景。
    if provider == "custom" or not base_url:
        base_url = base_url or _env("OPENAI_BASE_URL")
        model = model or _env("MODEL_NAME") or _env("OPENAI_MODEL")

    api_key = (
        _env("API_KEY")
        or _env(PROVIDER_KEY_ENV.get(provider, "PROVIDER_API_KEY"))
        or _env("OPENAI_API_KEY")
    )

    return Settings(
        provider=provider,
        provider_label=preset["label"],
        base_url=base_url.rstrip("/"),
        model=model,
        embedding_model=_env("EMBEDDING_MODEL") or preset.get("embedding_model", ""),
        api_key=api_key,
        temperature=float(_env("TEMPERATURE", "0.3")),
        max_tool_rounds=int(_env("MAX_TOOL_ROUNDS", "4")),
        request_timeout=float(_env("REQUEST_TIMEOUT", "60")),
        # 默认监听 0.0.0.0 以适配容器平台（Render 等），本地仍用 127.0.0.1 访问
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8000")),
        knowledge_dir=BASE_DIR / "knowledge",
        log_dir=BASE_DIR / "logs",
        data_dir=BASE_DIR / "data",
        tool_backend=_env("TOOL_BACKEND", "mock").lower(),
        tool_api_base=_env("TOOL_API_BASE").rstrip("/"),
        tool_api_key=_env("TOOL_API_KEY"),
        tool_api_key_header=_env("TOOL_API_KEY_HEADER", "Authorization"),
    )


settings = load_settings()
