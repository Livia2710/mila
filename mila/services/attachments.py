import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from mila.prompts import AUDIO_UNINTELLIGIBLE_REPLY, UNSUPPORTED_ATTACHMENT_REPLY
from mila.schemas import ChatResponse, ChatTurn
from mila.services.pipeline import process_question
from mila.services.safety import normalize

logger = logging.getLogger("mila.attachments")

AUDIO_TYPES = {
    ".webm": {"audio/webm"},
    ".ogg": {"audio/ogg", "application/ogg"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".mpeg": {"audio/mpeg"},
    ".mpga": {"audio/mpeg"},
    ".m4a": {"audio/mp4", "audio/x-m4a", "audio/m4a"},
    ".mp4": {"audio/mp4"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    ".flac": {"audio/flac", "audio/x-flac"},
}
WHISPER_SILENCE_HALLUCINATIONS = (
    "legendas pela comunidade",
    "legendas por amara",
    "obrigado por assistir",
    "obrigada por assistir",
    "inscreva-se no canal",
    "inscreva se no canal",
    "amara.org",
)


def parse_history(history: str) -> list[ChatTurn]:
    try:
        value = json.loads(history or "[]")
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError
        return TypeAdapter(list[ChatTurn]).validate_python(value)
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Histórico inválido.") from exc


def _is_audio(filename: str, content_type: str | None) -> bool:
    extension = Path(filename).suffix.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return extension in AUDIO_TYPES and mime in AUDIO_TYPES[extension]


def _usable_transcription(text: str) -> bool:
    normalized = normalize(text)
    useful_chars = sum(char.isalnum() for char in normalized)
    return useful_chars >= 3 and not any(item in normalized for item in WHISPER_SILENCE_HALLUCINATIONS)


def _response(runtime: Any, **kwargs: Any) -> ChatResponse:
    response = ChatResponse(**kwargs)
    if not runtime.settings.mila_debug:
        response.debug_info = {}
    return response


async def handle_attachment(
    file: UploadFile,
    message: str | None,
    history_json: str,
    runtime: Any,
) -> ChatResponse:
    history = parse_history(history_json)
    maximum = runtime.settings.attach_max_mb * 1024 * 1024
    temporary = tempfile.SpooledTemporaryFile(max_size=maximum, mode="w+b")
    size = 0
    try:
        while chunk := await file.read(64 * 1024):
            size += len(chunk)
            if size > maximum:
                logger.info("Anexo excedeu limite; bytes>%d", maximum)
                raise HTTPException(status_code=413, detail="O arquivo excede o tamanho máximo permitido.")
            temporary.write(chunk)
        if not _is_audio(file.filename or "", file.content_type):
            logger.info("Anexo não suportado; mime=%s bytes=%d", (file.content_type or "")[:80], size)
            return _response(runtime, response=UNSUPPORTED_ATTACHMENT_REPLY, intent="arquivo_nao_suportado")
        temporary.seek(0)
        try:
            transcript = runtime.transcription.transcribe(temporary, Path(file.filename or "audio").name)
        except Exception as exc:
            from mila.errors import TranscriptionUnavailable
            if isinstance(exc, TranscriptionUnavailable):
                raise
            raise TranscriptionUnavailable("A transcrição não está disponível.") from exc
        if not _usable_transcription(transcript):
            return _response(
                runtime,
                response=AUDIO_UNINTELLIGIBLE_REPLY,
                intent="audio_ininteligivel",
                transcription=transcript,
            )
        combined = f"{message.strip()}\n{transcript}".strip() if message and message.strip() else transcript
        if len(combined) > 4000:
            raise HTTPException(status_code=422, detail="O conteúdo transcrito excede o limite de texto.")
        result = process_question(combined, history, runtime)
        result.transcription = transcript
        return result
    finally:
        temporary.close()
        await file.close()

