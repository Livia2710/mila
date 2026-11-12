import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from mila.config import Settings
from mila.main import create_app
from mila.prompts import CRISIS_REPLY


class FakeLLM:
    def __init__(self, transcript="O que é o MindU?", routes=None):
        self.transcript = transcript
        self.routes = list(routes or [])
        self.calls = []

    def transcribe(self, file, filename):
        return self.transcript

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if "response_format" in kwargs:
            return self.routes.pop(0)
        return "Resposta do laboratório."


class FakeStore:
    class Collection:
        def count(self):
            return 1

    _collection = Collection()

    def similarity_search_with_relevance_scores(self, query, k):
        return [(Document(page_content="O MindU é uma plataforma de saúde mental corporativa.", metadata={"source": "01_sobre_mindu.pdf", "section": "1"}), 0.82)]


def _route(intent="sobre_mindu", confidence=0.95):
    return json.dumps({"intent": intent, "confidence": confidence, "secondary_intent": None, "data_target": None})


def _client(transcript="O que é o MindU?", *, debug=False, production=False, attach_max_mb=10):
    api_key = "test-secret" if production else None
    settings = Settings(
        _env_file=None,
        app_env="production" if production else "development",
        groq_api_key="test-key",
        mila_api_key=api_key,
        mila_debug=debug,
        attach_max_mb=attach_max_mb,
    )
    llm = FakeLLM(transcript=transcript, routes=[_route()])
    runtime = SimpleNamespace(
        settings=settings,
        llm=llm,
        transcription=llm,
        vectorstores={name: FakeStore() for name in ("sobre_mindu", "cadastro", "agendamento", "empresa")},
        live_data=SimpleNamespace(),
        close=lambda: None,
    )
    app = create_app(settings=settings, runtime_builder=lambda _: runtime)
    return TestClient(app), llm


def test_image_and_pdf_return_supported_product_message_without_llm():
    client, llm = _client()
    with client:
        for filename, mime in (("foto.png", "image/png"), ("manual.pdf", "application/pdf")):
            response = client.post("/chat/audio", files={"file": (filename, b"file bytes", mime)})
            assert response.status_code == 200
            assert response.json()["intent"] == "arquivo_nao_suportado"
    assert not llm.calls


def test_audio_is_transcribed_and_runs_the_text_pipeline():
    client, llm = _client()
    with client:
        response = client.post("/chat/audio", files={"file": ("question.webm", b"audio bytes", "audio/webm")})
    assert response.status_code == 200
    assert response.json()["transcription"] == "O que é o MindU?"
    assert response.json()["intent"] == "sobre_mindu"
    assert response.json()["response"] == "Resposta do laboratório."
    assert len(llm.calls) == 2


def test_transcribed_crisis_uses_fixed_reply_without_chat_llm():
    client, llm = _client(transcript="Não quero mais viver")
    with client:
        response = client.post("/chat/audio", files={"file": ("voice.m4a", b"audio bytes", "audio/mp4")})
    assert response.status_code == 200
    assert response.json()["intent"] == "crise"
    assert response.json()["response"] == CRISIS_REPLY
    assert not llm.calls


def test_unintelligible_audio_does_not_call_chat_pipeline():
    client, llm = _client(transcript="... uh")
    with client:
        response = client.post("/chat/audio", files={"file": ("silence.wav", b"audio bytes", "audio/wav")})
    assert response.status_code == 200
    assert response.json()["intent"] == "audio_ininteligivel"
    assert not llm.calls


def test_audio_over_limit_returns_413():
    client, llm = _client(attach_max_mb=1)
    with client:
        response = client.post("/chat/audio", files={"file": ("large.wav", b"0" * (1024 * 1024 + 1), "audio/wav")})
    assert response.status_code == 413
    assert not llm.calls


def test_production_api_key_is_required_and_health_is_public():
    client, _ = _client(production=True)
    with client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.post("/chat", json={"message": "Oi"}).status_code == 401


def test_validation_error_does_not_echo_sensitive_input():
    client, _ = _client()
    secret_text = "dados de saúde sensíveis " * 200
    with client:
        response = client.post("/chat", json={"message": secret_text})
    assert response.status_code == 422
    assert secret_text not in response.text

