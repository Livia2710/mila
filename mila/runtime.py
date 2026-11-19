from dataclasses import dataclass

import httpx
from typing import Any

from mila.config import Settings
from mila.knowledge.ingest import prepare_knowledge_bases
from mila.services.llm import LLMService
from mila.services.live_data import LiveDataService
from mila.services.transcription import TranscriptionService


@dataclass
class Runtime:
    settings: Settings
    llm: LLMService
    transcription: TranscriptionService
    embeddings: Any
    vectorstores: dict[str, Any]
    http_client: httpx.Client
    live_data: LiveDataService

    def close(self) -> None:
        self.http_client.close()


def build_runtime(settings: Settings) -> Runtime:
    from langchain_huggingface import HuggingFaceEmbeddings

    llm = LLMService(settings)
    transcription = TranscriptionService(settings, client=llm.client)
    embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
    stores = prepare_knowledge_bases(settings, embedder=embeddings)
    http_client = httpx.Client(
        base_url=settings.mindu_api_url.rstrip("/"),
        timeout=settings.mindu_api_timeout_s,
    )
    return Runtime(
        settings=settings,
        llm=llm,
        transcription=transcription,
        embeddings=embeddings,
        vectorstores=stores,
        http_client=http_client,
        live_data=LiveDataService(settings, http_client),
    )

