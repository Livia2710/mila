import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from mila.schemas import ChatRequest, ChatResponse
from mila.security import require_api_key
from mila.services.attachments import handle_attachment
from mila.services.pipeline import process_question

logger = logging.getLogger("mila.http")
router = APIRouter()


def _runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="A Mila ainda está inicializando.")
    return runtime


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    runtime = _runtime(request)
    return process_question(payload.message.strip(), payload.history, runtime)


@router.post("/chat/audio", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat_audio(
    request: Request,
    file: UploadFile = File(...),
    message: str | None = Form(default=None, max_length=4000),
    history: str = Form(default="[]"),
) -> ChatResponse:
    runtime = _runtime(request)
    try:
        return await handle_attachment(file, message, history, runtime)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Dados do anexo inválidos.") from exc

