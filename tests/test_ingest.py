import shutil
from pathlib import Path

from langchain_core.embeddings.fake import DeterministicFakeEmbedding

from mila.config import Settings
from mila.knowledge.ingest import INTENTS, _digest, build_chunks, clean_legacy_collections, prepare_knowledge_bases


PROJECT = Path(__file__).resolve().parents[1]


def test_chunks_exclude_test_questions_and_include_source_section_intent():
    docs_dir = PROJECT / "documentos"
    chunks = build_chunks("sobre_mindu", *INTENTS["sobre_mindu"], docs_dir)
    assert chunks
    assert all("exemplos de perguntas" not in chunk.page_content.casefold() for chunk in chunks)
    assert all(chunk.metadata["intent"] == "sobre_mindu" for chunk in chunks)
    assert all(chunk.metadata["source"] == "01_sobre_mindu.pdf" for chunk in chunks)
    assert all(chunk.metadata["section"] for chunk in chunks)
    assert any("plataforma de saúde mental corporativa" in chunk.page_content.casefold() for chunk in chunks)


def test_short_sections_are_merged_and_long_sections_are_split():
    docs_dir = PROJECT / "documentos"
    chunks = build_chunks("agendamento", *INTENTS["agendamento"], docs_dir)
    assert any("1.1 Tipos de profissional" in chunk.page_content for chunk in chunks)
    assert all(len(chunk.page_content) <= 1000 for chunk in chunks)


def test_pdf_digest_changes_when_ingestion_parameters_change(tmp_path, monkeypatch):
    source = PROJECT / "documentos" / "01_sobre_mindu.pdf"
    copied = tmp_path / source.name
    shutil.copyfile(source, copied)
    first = _digest(copied)
    monkeypatch.setattr("mila.knowledge.ingest.CHUNK_OVERLAP", 99)
    assert _digest(copied) != first


def test_ingestion_is_idempotent(tmp_path):
    docs_dir = tmp_path / "docs"
    shutil.copytree(PROJECT / "documentos", docs_dir)
    chroma_dir = tmp_path / "chroma"
    settings = Settings(groq_api_key="test", _env_file=None)
    embeddings = DeterministicFakeEmbedding(size=384)
    first = prepare_knowledge_bases(settings, embeddings, docs_dir, chroma_dir)
    counts_first = {key: store._collection.count() for key, store in first.items()}
    second = prepare_knowledge_bases(settings, embeddings, docs_dir, chroma_dir)
    counts_second = {key: store._collection.count() for key, store in second.items()}
    assert counts_first == counts_second
    assert set(first) == set(INTENTS)


def test_legacy_cleanup_only_removes_old_intent_folders(tmp_path):
    for name in (*INTENTS.keys(), "sobre_mindu_cosine", "sobre_mindu_cosine_v2"):
        (tmp_path / name).mkdir()
    removed = clean_legacy_collections(tmp_path)
    assert set(removed) == {*INTENTS, "sobre_mindu_cosine"}
    assert (tmp_path / "sobre_mindu_cosine_v2").exists()

