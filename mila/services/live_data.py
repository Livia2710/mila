import json
import logging
import threading
import time
from typing import Any

import httpx

from mila.config import Settings
from mila.errors import LiveDataUnavailable
from mila.services.safety import normalize

logger = logging.getLogger("mila.live_data")


class LiveDataService:
    def __init__(self, settings: Settings, client: httpx.Client) -> None:
        self.settings = settings
        self.client = client
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def filters_for(self, question: str, target: str) -> dict[str, str]:
        if target == "planos":
            return {}
        text = normalize(question)
        params: dict[str, str] = {}
        modalities = (("online", "VIRTUAL"), ("virtual", "VIRTUAL"), ("presencial", "PRESENCIAL"), ("hibrido", "HIBRIDO"))
        for term, value in modalities:
            if term in text:
                params["modalidade"] = value
                break
        for specialty in self.settings.specialty_terms:
            normalized = normalize(specialty)
            if normalized and normalized in text:
                params["especialidade"] = specialty
                break
        return params

    def records(self, target: str, params: dict[str, str]) -> list[dict[str, Any]]:
        endpoint = "/v1/planos" if target == "planos" else "/v1/profissionais"
        key = (endpoint, tuple(sorted(params.items())))
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
        try:
            response = self.client.get(endpoint, params=params)
            response.raise_for_status()
            records = response.json()
            if not isinstance(records, list):
                raise ValueError("Resposta do catálogo inválida")
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Consulta de dados ao vivo falhou; alvo=%s tipo=%s", target, type(exc).__name__)
            raise LiveDataUnavailable("Os dados atualizados não estão disponíveis.") from exc

        if target == "planos":
            public = [{key: record.get(key) for key in (
                "nome", "vagasTotais", "porteIndicado",
                "precoMensalPorColaborador", "consultasSemLimite",
            )} for record in records]
            ttl = 300
        else:
            public = [{key: record.get(key) for key in ("nome", "tipo", "bio", "tags")} for record in records]
            ttl = 60
        with self._lock:
            self._cache[key] = (now + ttl, public[:40])
        return public[:40]

    @staticmethod
    def model_context(records: list[dict[str, Any]]) -> str:
        return json.dumps(records, ensure_ascii=False)

