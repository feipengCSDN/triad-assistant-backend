from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = ""
    asr_base_url: str = ""
    asr_api_key: str = ""
    asr_model: str = "whisper-1"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    http_timeout_seconds: float = 60
    llm_max_tokens: int = 512
    llm_metadata_max_tokens: int = 1024
    max_audio_bytes: int = 26_214_400

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
