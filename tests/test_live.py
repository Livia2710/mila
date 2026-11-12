import re
import time

import pytest
from fastapi.testclient import TestClient

from mila.config import get_settings
from mila.main import app


def _wait_for_ready(client: TestClient, timeout_s: int = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if client.get("/ready").status_code == 200:
            return
        time.sleep(1)
    raise AssertionError("Mila não ficou pronta no tempo esperado.")


@pytest.mark.live
def test_live_answers_a_documented_question_and_does_not_invent_support_phone():
    settings = get_settings()
    headers = {"X-Mila-API-Key": settings.mila_api_key} if settings.mila_api_key else {}
    with TestClient(app) as client:
        _wait_for_ready(client)
        documented = client.post("/chat", json={"message": "A Mila pode fazer diagnóstico?"}, headers=headers)
        assert documented.status_code == 200
        assert "diagnóstico" in documented.json()["response"].casefold()
        unknown = client.post("/chat", json={"message": "Qual é o telefone do suporte do MindU?"}, headers=headers)
        assert unknown.status_code == 200
        assert not re.search(r"\b\d{8,}\b", unknown.json()["response"])

