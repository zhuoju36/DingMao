"""应用配置。集中管理，禁止散落各处硬编码。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 .env 加载配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ====== 应用 ======
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_secret_key: str = Field(min_length=32)
    app_cors_origins: str = "http://localhost:5173"

    # ====== 数据库 ======
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "dingmao"
    postgres_password: str = "dingmao_dev_password"
    postgres_db: str = "dingmao"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ====== Redis ======
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ====== LLM - MiniMax ======
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-M3"

    # ====== LLM - DeepSeek ======
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    # ====== LLM - OpenAI 兜底 ======
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # ====== LLM 路由 ======
    llm_default: Literal["minimax", "deepseek", "openai"] = "minimax"
    llm_timeout: int = 60
    llm_max_retries: int = 2

    # ====== 腾讯云 COS ======
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = "ap-guangzhou"
    cos_bucket: str = "dingmao-files-dev"

    # ====== 文件存储（P0-7-A）======
    # MVP 只用本地存储，V2 加 COS
    # 相对 cwd 的路径：本地 backend/ 下 = "storage"，Docker /app 下 = "storage"
    storage_root: str = "storage"

    # ====== JWT ======
    jwt_secret_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """单例 Settings。"""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
