from pathlib import Path

import pytest
import yaml
from langchain_huggingface import HuggingFaceEmbeddings

from mila.config import Settings
from mila.knowledge.ingest import prepare_knowledge_bases
from mila.services.safety import normalize

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.recovery
def test_golden_questions_retrieve_expected_content_and_reject_out_of_scope(tmp_path):
    settings = Settings(_env_file=None, groq_api_key="test")
    embedder = HuggingFaceEmbeddings(model_name=settings.embedding_model)
    stores = prepare_knowledge_bases(
        settings,
        embedder=embedder,
        docs_dir=PROJECT / "documentos",
        chroma_dir=tmp_path / "chroma",
    )
    cases = yaml.safe_load((PROJECT / "tests" / "golden_questions.yaml").read_text(encoding="utf-8"))
    in_scope_scores = []
    outside_scores = []
    failures = []
    for case in cases:
        matches = stores[case["intent"]].similarity_search_with_relevance_scores(case["question"], k=settings.rag_top_k)
        scores = [float(score) for _, score in matches]
        if case.get("outside_scope"):
            outside_scores.append(max(scores, default=0.0))
            if not scores or max(scores) >= settings.rag_min_relevance:
                failures.append((case["question"], scores, "fora do escopo aceito"))
        else:
            in_scope_scores.extend(score for score in scores if score >= settings.rag_min_relevance)
            expected = normalize(case["expected"])
            accepted = [doc for doc, score in matches if float(score) >= settings.rag_min_relevance]
            retrieved = normalize("\n".join(doc.page_content for doc in accepted))
            if not accepted or expected not in retrieved:
                failures.append((case["question"], scores, f"esperado: {case['expected']}"))
    assert not failures, (
        f"falhas={failures}; menor score dentro do escopo={min(in_scope_scores, default=None)}; "
        f"maior score fora do escopo={max(outside_scores, default=None)}; "
        f"limite={settings.rag_min_relevance}"
    )

