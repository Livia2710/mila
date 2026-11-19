from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Intent = Literal[
    "saudacao",
    "crise",
    "sobre_mindu",
    "cadastro",
    "agendamento",
    "empresa",
    "dados_banco",
    "normal",
    "esclarecimento",
    "arquivo_nao_suportado",
    "audio_ininteligivel",
]
RouteIntent = Literal[
    "saudacao",
    "crise",
    "sobre_mindu",
    "cadastro",
    "agendamento",
    "empresa",
    "dados_banco",
    "normal",
]
DataTarget = Literal["planos", "profissionais"]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    response: str
    intent: Intent
    sources: list[str] = Field(default_factory=list)
    missing_info: bool = False
    debug_info: dict = Field(default_factory=dict)
    transcription: str | None = None


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: RouteIntent
    confidence: float = Field(ge=0, le=1)
    secondary_intent: RouteIntent | None
    data_target: DataTarget | None

