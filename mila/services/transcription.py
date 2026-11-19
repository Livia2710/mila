import logging
from typing import Any

from groq import Groq

from mila.config import Settings
from mila.errors import TranscriptionUnavailable

logger = logging.getLogger("mila.transcription")


class TranscriptionService:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or Groq(
            api_key=settings.groq_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )

    def transcribe(self, audio_file: Any, filename: str) -> str:
        try:
            result = self.client.audio.transcriptions.create(
                file=(filename, audio_file),
                model=self.settings.groq_stt_model,
                language="pt",
                temperature=0,
                timeout=self.settings.llm_timeout_s,
            )
            return str(result.text or "").strip()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            logger.error("Whisper indisponível; tipo=%s status=%s", type(exc).__name__, status)
            raise TranscriptionUnavailable("O serviço de transcrição está indisponível.") from exc

