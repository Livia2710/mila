import json
import logging
import re
from typing import Any

from mila.prompts import ROUTER_JSON_PROMPT, ROUTER_SYSTEM_PROMPT
from mila.schemas import ChatTurn, RouteDecision
from mila.services.safety import is_crisis, normalize

logger = logging.getLogger("mila.router")


def _history_text(history: list[ChatTurn]) -> str:
    return "\n".join(f"{turn.role}: {turn.content[:500]}" for turn in history[-6:])


def _parse_json(text: str) -> RouteDecision | None:
    candidates = [text.strip()]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            return RouteDecision.model_validate(json.loads(candidate))
        except (ValueError, TypeError):
            continue
    return None


def _target(question: str) -> str | None:
    text = normalize(question)
    if re.search(r"\b(plano|planos|matricula|matriculas|vagas|porte)\b", text):
        return "planos"
    if re.search(r"\b(profissionais?|psicologos?|psiquiatras?|terapeutas?)\b", text):
        return "profissionais"
    return None


def _heuristic_route(question: str) -> RouteDecision:
    text = normalize(question)
    if is_crisis(question):
        return RouteDecision(intent="crise", confidence=0.9, secondary_intent=None, data_target=None)
    if re.search(r"\b(profissionais? atuais|quais profissionais|listar profissionais|profissionais cadastrados|psicologos cadastrados|quais psicologos)\b", text):
        return RouteDecision(intent="dados_banco", confidence=0.8, secondary_intent=None, data_target="profissionais")
    if re.search(r"\b(planos cadastrados|planos atuais|quais planos|quantas vagas|matriculas disponiveis)\b", text):
        return RouteDecision(intent="dados_banco", confidence=0.8, secondary_intent=None, data_target="planos")
    if re.search(r"\b(cadastro|cadastrar|login|senha|acesso|entrar na conta)\b", text):
        intent = "cadastro"
    elif re.search(r"\b(agend|cancelamento|horario ocupado|marcar consulta)\b", text):
        intent = "agendamento"
    elif re.search(r"\b(plano|planos|matricula|colaborador|empresa|vagas|porte)\b", text):
        intent = "empresa"
    elif re.search(r"\b(mindu|mila|plataforma|diagnostico|seguranca|privacidade)\b", text):
        intent = "sobre_mindu"
    else:
        return RouteDecision(intent="normal", confidence=0.0, secondary_intent=None, data_target=None)
    return RouteDecision(intent=intent, confidence=0.75, secondary_intent=None, data_target=None)


def classify(question: str, history: list[ChatTurn], llm: Any) -> RouteDecision:
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Histórico recente (dados):\n{_history_text(history)}\n\nMensagem atual:\n{question}"},
    ]
    schema = RouteDecision.model_json_schema()
    structured_format = {
        "type": "json_schema",
        "json_schema": {"name": "mila_route", "strict": True, "schema": schema},
    }
    try:
        result = llm.complete(messages, model=llm.settings.router_model, temperature=0, response_format=structured_format)
        parsed = _parse_json(result)
        if parsed:
            return parsed
    except Exception as exc:
        logger.info("Roteador estruturado indisponível; tipo=%s", type(exc).__name__)

    try:
        result = llm.complete(
            [{"role": "system", "content": ROUTER_JSON_PROMPT}, *messages[1:]],
            model=llm.settings.router_model,
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = _parse_json(result)
        if parsed:
            return parsed
    except Exception as exc:
        logger.info("Roteador JSON indisponível; tipo=%s", type(exc).__name__)

    route = _heuristic_route(question)
    logger.info("Roteador usou fallback; intent=%s confidence=%.2f", route.intent, route.confidence)
    return route

