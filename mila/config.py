from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    groq_model_router: str | None = None
    groq_stt_model: str = "whisper-large-v3-turbo"
    llm_timeout_s: float = Field(default=30, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    mila_api_key: str | None = None
    mila_debug: bool = False
    mindu_api_url: str = "http://localhost:8080"
    mindu_api_timeout_s: float = Field(default=8, gt=0)
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_min_relevance: float = Field(default=0.4, ge=-1, le=1)
    rag_rewrite_followups: bool = False
    router_min_confidence: float = Field(default=0.6, ge=0, le=1)
    history_max_turns: int = Field(default=8, ge=0, le=20)
    attach_max_mb: int = Field(default=10, ge=1, le=50)
    log_level: str = "INFO"
    specialties: str = "ansiedade,depressao,luto,estresse,relacionamento,sono,autismo,tdah"

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY é obrigatória.")
        if self.app_env.lower() == "production" and not self.mila_api_key:
            raise ValueError("MILA_API_KEY é obrigatória em APP_ENV=production.")
        return self

    @property
    def router_model(self) -> str:
        return self.groq_model_router or self.groq_model

    @property
    def specialty_terms(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.specialties.split(",") if item.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

