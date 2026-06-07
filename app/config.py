from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_model: str = "MiniMax-M2.5"

    # ---- 语义缓存 ----
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.9
    cache_max_temperature: float = 0.5
    cache_max_entries: int = 10000
    embed_model: str = "BAAI/bge-small-en-v1.5"
    vector_store_backend: str = "memory"  # "memory" | "redis"
    redis_url: str = "redis://localhost:6379"


settings = Settings()
