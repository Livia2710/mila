import logging
import re
import time
from typing import Any

from mila.prompts import (
    CLARIFICATION_REPLY,
    CRISIS_REPLY,
    GREETING_REPLY,
    LIVE_DATA_SYSTEM_PROMPT,
    NORMAL_SYSTEM_PROMPT,
)
from mila.schemas import ChatResponse, ChatTurn, RouteDecision
from mila.services.intent_router import classify
from mila.services.rag import answer_from_rag
from mila.services.safety import is_crisis, is_only_symbols, is_simple_greeting, normalize

logger = logging.getLogger("mila.pipeline")

INTENT_LABELS = {
    "sobre_mindu": "o funcionamento do MindU",
    "cadastro": "cadastro e acesso",
    "agendamento": "agendamentos",
    "empresa": "planos e empresas",
    "dados_banco": "profissionais e planos atuais",
    "normal": "outro assunto",
}


def _response(runtime: Any, **kwargs: Any) -> ChatResponse:
    response = ChatResponse(**kwargs)
    if not runtime.settings.mila_debug:
        response.debug_info = {}
    return response


def _history_messages(history: list[ChatTurn], max_turns: int) -> list[dict[str, str]]:
    return [
        {"role": turn.role, "content": turn.content[:1500]}
        for turn in history[-max_turns:]
    ] if max_turns else []


def _live_answer(question: str, history: list[ChatTurn], route: RouteDecision, runtime: Any) -> ChatResponse:
    target = route.data_target or _fallback_data_target(question)
    if target is None:
        return _response(runtime, response=CLARIFICATION_REPLY, intent="esclarecimento", missing_info=True)
    params = runtime.live_data.filters_for(question, target)
    records = runtime.live_data.records(target, params)
    source = "API Java / PostgreSQL"
    if not records:
        return _response(
            runtime,
            response="Não encontrei registros correspondentes no catálogo atual do MindU. Tente mudar os filtros ou peça outra busca.",
            intent="dados_banco",
            sources=[source],
            missing_info=True,
            debug_info={"alvo": target, "filtros": params, "registros": 0},
        )
    context = runtime.live_data.model_context(records)
    messages = [
        {"role": "system", "content": LIVE_DATA_SYSTEM_PROMPT},
        *_history_messages(history, runtime.settings.history_max_turns),
        {"role": "user", "content": f"Registros atuais do backend:\n{context}\n\nPergunta: {question}"},
    ]
    answer = runtime.llm.complete(messages)
    return _response(
        runtime,
        response=answer,
        intent="dados_banco",
        sources=[source],
        debug_info={"alvo": target, "filtros": params, "registros": len(records), "amostra": records[:5]},
    )


def _fallback_data_target(question: str) -> str | None:
    text = normalize(question)
    if re.search(r"\b(plano|planos|matricula|matriculas|vagas|porte)\b", text):
        return "planos"
    if re.search(r"\b(profissionais?|psicologos?|psiquiatras?|terapeutas?)\b", text):
        return "profissionais"
    return None


def _process(question: str, history: list[ChatTurn], runtime: Any) -> ChatResponse:
    if is_crisis(question):
        logger.info("Evento de crise detectado pela regra de segurança")
        return _response(runtime, response=CRISIS_REPLY, intent="crise", debug_info={"rota": "regra fixa de segurança"})
    if is_only_symbols(question):
        return _response(runtime, response=GREETING_REPLY, intent="saudacao")
    if is_simple_greeting(question):
        return _response(runtime, response=GREETING_REPLY, intent="saudacao")

    route = classify(question, history, runtime.llm)
    if route.intent == "crise":
        logger.info("Evento de crise detectado pelo roteador")
        return _response(runtime, response=CRISIS_REPLY, intent="crise", debug_info={"rota": "roteador; resposta fixa"})
    if route.intent == "saudacao":
        return _response(runtime, response=GREETING_REPLY, intent="saudacao")
    if route.confidence < runtime.settings.router_min_confidence:
        return _response(runtime, response=CLARIFICATION_REPLY, intent="esclarecimento", missing_info=True)

    if route.intent == "dados_banco":
        return _live_answer(question, history, route, runtime)
    if route.intent == "normal":
        messages = [
            {"role": "system", "content": NORMAL_SYSTEM_PROMPT},
            *_history_messages(history, runtime.settings.history_max_turns),
            {"role": "user", "content": question},
        ]
        response = _response(runtime, response=runtime.llm.complete(messages), intent="normal")
    else:
        response = answer_from_rag(question, history, route.intent, runtime)
        if not runtime.settings.mila_debug:
            response.debug_info = {}

    secondary = route.secondary_intent
    if secondary and secondary != route.intent and secondary not in {"crise", "saudacao"}:
        label = INTENT_LABELS.get(secondary)
        if label:
            response.response += f"\n\nSe quiser, também posso ajudar com {label}."
    return response


def process_question(question: str, history: list[ChatTurn] | None, runtime: Any) -> ChatResponse:
    turns = history or []
    started = time.monotonic()
    response = _process(question, turns, runtime)
    logger.info(
        "Chat concluído; intent=%s missing_info=%s message_chars=%d history_turns=%d latency_ms=%d",
        response.intent,
        response.missing_info,
        len(question),
        len(turns),
        int((time.monotonic() - started) * 1000),
    )
    return response

