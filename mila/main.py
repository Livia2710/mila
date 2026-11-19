import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mila.config import Settings
from mila.errors import KnowledgeBaseUnavailable, LiveDataUnavailable, LLMUnavailable, MilaError, TranscriptionUnavailable
from mila.routers.chat import router as chat_router
from mila.routers.health import router as health_router
from mila.runtime import Runtime, build_runtime

logger = logging.getLogger("mila")


def create_app(
    settings: Settings | None = None,
    runtime_builder: Callable[[Settings], Runtime] = build_runtime,
) -> FastAPI:
    resolved_settings = settings or Settings()
    logging.basicConfig(level=getattr(logging, resolved_settings.log_level.upper(), logging.INFO))
    logging.getLogger("mila").setLevel(getattr(logging, resolved_settings.log_level.upper(), logging.INFO))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.runtime = None
        app.state.startup_error = None

        async def initialize() -> None:
            try:
                app.state.runtime = await asyncio.to_thread(runtime_builder, resolved_settings)
                logger.info("Inicialização concluída; coleções=%d", len(app.state.runtime.vectorstores))
            except Exception as exc:
                app.state.startup_error = type(exc).__name__
                logger.error("Inicialização falhou; tipo=%s", type(exc).__name__)

        task = asyncio.create_task(initialize())
        try:
            yield
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            runtime = app.state.runtime
            if runtime is not None:
                runtime.close()

    app = FastAPI(title="Mila - Assistente MindU", version="2.0.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(chat_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Dados da solicitação inválidos."})

    @app.exception_handler(KnowledgeBaseUnavailable)
    async def knowledge_error(_: Request, __: KnowledgeBaseUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "A base de conhecimento não está disponível."})

    @app.exception_handler(LiveDataUnavailable)
    async def live_data_error(_: Request, __: LiveDataUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Não consegui consultar os dados atualizados. Tente novamente em instantes."})

    @app.exception_handler(LLMUnavailable)
    @app.exception_handler(TranscriptionUnavailable)
    async def llm_error(_: Request, __: MilaError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "Não foi possível obter uma resposta agora."})

    @app.exception_handler(MilaError)
    async def mila_error(_: Request, __: MilaError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "Não foi possível processar a solicitação agora."})

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Falha inesperada; tipo=%s", type(exc).__name__)
        return JSONResponse(status_code=502, content={"detail": "Não foi possível obter uma resposta agora."})

    return app


app = create_app()

