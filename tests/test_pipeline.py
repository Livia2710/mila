import json
from types import SimpleNamespace

from langchain_core.documents import Document

from mila.config import Settings
from mila.prompts import CRISIS_REPLY
from mila.schemas import ChatTurn
from mila.services.intent_router import classify
from mila.services.pipeline import process_question


class FakeLLM:
    def __init__(self, routes=None, answers=None, failures=0):
        self.settings = SimpleNamespace(router_model="fake-router", groq_model="fake")
        self.routes = list(routes or [])
        self.answers = list(answers or [])
        self.failures = failures
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if "response_format" in kwargs:
            if self.failures:
                self.failures -= 1
                raise RuntimeError("provider unavailable")
            return self.routes.pop(0)
        return self.answers.pop(0) if self.answers else "resposta de teste"


class FakeStore:
    def __init__(self, matches):
        self.matches = matches

    def similarity_search_with_relevance_scores(self, query, k):
        return self.matches[:k]


def _route(intent, confidence=0.95, data_target=None, secondary_intent=None):
    return json.dumps({
        "intent": intent,
        "confidence": confidence,
        "secondary_intent": secondary_intent,
        "data_target": data_target,
    })


def _runtime(llm, *, debug=False, matches=None):
    settings = Settings(groq_api_key="test", _env_file=None, mila_debug=debug)
    return SimpleNamespace(
        settings=settings,
        llm=llm,
        vectorstores={"sobre_mindu": FakeStore(matches or [])},
        live_data=SimpleNamespace(
            filters_for=lambda question, target: {},
            records=lambda target, params: [{"nome": "Plano de teste"}],
            model_context=lambda records: json.dumps(records),
        ),
    )


def test_router_classified_crisis_uses_fixed_response_without_answer_call():
    llm = FakeLLM(routes=[_route("crise")])
    response = process_question("Estou em sofrimento agora.", [], _runtime(llm))
    assert response.intent == "crise"
    assert response.response == CRISIS_REPLY
    assert len(llm.calls) == 1


def test_low_router_confidence_returns_clarification_without_answer_call():
    llm = FakeLLM(routes=[_route("normal", confidence=0.2)])
    response = process_question("Uma pergunta ambígua", [], _runtime(llm))
    assert response.intent == "esclarecimento"
    assert response.missing_info
    assert len(llm.calls) == 1


def test_greeting_skips_llm():
    llm = FakeLLM()
    response = process_question("Oi! 😊", [], _runtime(llm))
    assert response.intent == "saudacao"
    assert not llm.calls


def test_crisis_regex_skips_llm():
    llm = FakeLLM()
    response = process_question("Não quero mais viver", [], _runtime(llm))
    assert response.intent == "crise"
    assert response.response == CRISIS_REPLY
    assert not llm.calls


def test_rag_only_sends_chunks_above_threshold_to_model():
    docs = [
        (Document(page_content="contexto bom", metadata={"source": "01.pdf", "section": "1"}), 0.82),
        (Document(page_content="ruído irrelevante", metadata={"source": "01.pdf", "section": "2"}), 0.12),
        (Document(page_content="outro contexto bom", metadata={"source": "01.pdf", "section": "3"}), 0.42),
    ]
    llm = FakeLLM(routes=[_route("sobre_mindu")], answers=["resposta fundamentada"])
    runtime = _runtime(llm, debug=True, matches=docs)
    response = process_question("O que é o MindU?", [], runtime)
    answer_messages = llm.calls[-1][0]
    context_message = answer_messages[-1]["content"]
    assert response.response == "resposta fundamentada"
    assert "contexto bom" in context_message
    assert "outro contexto bom" in context_message
    assert "ruído irrelevante" not in context_message
    assert response.debug_info["trechos_aceitos"] == 2


def test_debug_info_is_empty_when_debug_disabled():
    docs = [(Document(page_content="contexto", metadata={"source": "01.pdf"}), 0.8)]
    llm = FakeLLM(routes=[_route("sobre_mindu")], answers=["resposta"])
    response = process_question("O que é o MindU?", [], _runtime(llm, matches=docs))
    assert response.debug_info == {}


def test_router_falls_back_to_json_mode_then_validates_schema():
    llm = FakeLLM(routes=[_route("cadastro")], failures=1)
    route = classify("Como faço cadastro?", [], llm)
    assert route.intent == "cadastro"
    assert len(llm.calls) == 2
    assert llm.calls[1][1]["response_format"] == {"type": "json_object"}


def test_router_uses_heuristic_after_both_model_routes_fail():
    llm = FakeLLM(failures=2)
    route = classify("Como faço meu cadastro?", [], llm)
    assert route.intent == "cadastro"
    assert route.confidence > 0


def test_unmatched_router_fallback_has_zero_confidence():
    llm = FakeLLM(failures=2)
    route = classify("Escreva um poema sobre astronomia", [], llm)
    assert route.intent == "normal"
    assert route.confidence == 0


def test_history_passes_only_recent_turns_to_the_router():
    llm = FakeLLM(routes=[_route("sobre_mindu")])
    history = [ChatTurn(role="user", content=f"turno {index}") for index in range(10)]
    classify("O que é o MindU?", history, llm)
    prompt = llm.calls[0][0][-1]["content"]
    assert "turno 0" not in prompt
    assert "turno 9" in prompt

