"""Configuração via variáveis de ambiente."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_token: str = ""
    max_upload_mb: int = 50
    host: str = "0.0.0.0"
    port: int = 8000

    # DPI do render para OCR (maior = mais preciso e mais lento)
    ocr_dpi: int = 250
    # force_ocr=True aplica OCR mesmo com texto digital (mais lento)
    force_ocr: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
