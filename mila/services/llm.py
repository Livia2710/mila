import logging
from typing import Any

from groq import Groq

from mila.config import Settings
from mila.errors import LLMUnavailable

logger = logging.getLogger("mila.llm")


class LLMService:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or Groq(
            api_key=settings.groq_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or self.settings.groq_model,
            "messages": messages,
            "temperature": temperature,
            "timeout": self.settings.llm_timeout_s,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            result = self.client.chat.completions.create(**kwargs)
            content = result.choices[0].message.content or ""
            return content.strip()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            logger.error("LLM indisponível; tipo=%s status=%s", type(exc).__name__, status)
            raise LLMUnavailable("O serviço de linguagem está indisponível.") from exc

