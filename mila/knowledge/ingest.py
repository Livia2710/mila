import argparse
import hashlib
import logging
import re
import shutil
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

if TYPE_CHECKING:
    from langchain_chroma import Chroma
else:
    Chroma = Any

from mila.config import PROJECT_DIR, Settings
from mila.errors import KnowledgeBaseUnavailable

logger = logging.getLogger("mila.knowledge")

INTENTS = {
    "sobre_mindu": ("01_sobre_mindu.pdf", "MindU: Sobre a plataforma"),
    "cadastro": ("02_cadastro_e_acesso.pdf", "MindU: Cadastro e acesso"),
    "agendamento": ("03_agendamento_e_profissionais.pdf", "MindU: Agendamento e profissionais"),
    "empresa": ("04_empresas_e_planos.pdf", "MindU: Empresas, planos e matrículas"),
}
CHROMA_METRIC = "cosine"
COLLECTION_VERSION = "cosine_v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
SHORT_SECTION_CHARS = 200
INGESTION_VERSION = "sections-v2;strip-test-questions-v1;prefix-title-v1"
SECTION_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\.\s+(.+?)\s*$", re.MULTILINE)


def _plain(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


def _strip_test_questions(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "exemplos de perguntas" in _plain(line):
            return "\n".join(lines[:index]).strip()
    return text.strip()


def _sections(text: str) -> list[tuple[str, str, str]]:
    matches = list(SECTION_PATTERN.finditer(text))
    if not matches:
        return [("Introdução", "", text.strip())] if text.strip() else []
    sections: list[tuple[str, str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("Introdução", "", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        number, title = match.group(1), match.group(2).strip()
        body = text[match.end():end].strip()
        sections.append((number, title, body))
    return sections


def _merge_short_sections(sections: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    merged: list[tuple[str, str, str]] = []
    index = 0
    while index < len(sections):
        number, title, body = sections[index]
        label = f"{number}. {title}".strip(". ")
        if len(body) < SHORT_SECTION_CHARS and len(sections) > 1:
            if index + 1 < len(sections):
                next_number, next_title, next_body = sections[index + 1]
                next_label = f"{next_number}. {next_title}".strip(". ")
                sections[index + 1] = (
                    next_number,
                    f"{label} + {next_label}",
                    f"{body}\n\n{next_body}".strip(),
                )
                index += 1
                continue
            if merged:
                prev_number, prev_title, prev_body = merged.pop()
                merged.append((prev_number, f"{prev_title} + {label}", f"{prev_body}\n\n{body}".strip()))
                index += 1
                continue
        merged.append((number, title, body))
        index += 1
    return merged


def build_chunks(intent: str, filename: str, title: str, docs_dir: Path) -> list[Document]:
    reader = PdfReader(str(docs_dir / filename))
    text = _strip_test_questions("\n".join(page.extract_text() or "" for page in reader.pages))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[Document] = []
    for number, section_title, body in _merge_short_sections(_sections(text)):
        section = f"{number}. {section_title}".strip(". ")
        prefix = f"{title} — {section}\n" if section else f"{title}\n"
        for part in splitter.split_text(body):
            content = prefix + part
            if len(content) > CHUNK_SIZE + 200:
                logger.warning("Trecho acima do alvo após prefixo; intent=%s section=%s chars=%d", intent, section, len(content))
            chunks.append(Document(
                page_content=content,
                metadata={"source": filename, "section": section, "intent": intent},
            ))
    if not chunks:
        raise KnowledgeBaseUnavailable(f"Nenhum texto útil foi extraído de {filename}.")
    return chunks


def _digest(pdf_path: Path) -> str:
    parameters = (
        f"{INGESTION_VERSION};chunk_size={CHUNK_SIZE};overlap={CHUNK_OVERLAP};"
        f"short={SHORT_SECTION_CHARS};metric={CHROMA_METRIC}"
    )
    return hashlib.sha256(pdf_path.read_bytes() + parameters.encode("utf-8")).hexdigest()


def prepare_knowledge_bases(
    settings: Settings,
    embedder=None,
    docs_dir: Path | None = None,
    chroma_dir: Path | None = None,
) -> dict[str, Chroma]:
    docs_dir = docs_dir or PROJECT_DIR / "documentos"
    chroma_dir = chroma_dir or PROJECT_DIR / "dados" / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    if embedder is None:
        from langchain_huggingface import HuggingFaceEmbeddings

        embedder = HuggingFaceEmbeddings(model_name=settings.embedding_model)
    from langchain_chroma import Chroma
    stores: dict[str, Chroma] = {}
    try:
        for intent, (filename, title) in INTENTS.items():
            pdf_path = docs_dir / filename
            if not pdf_path.is_file():
                raise KnowledgeBaseUnavailable(f"Documento obrigatório ausente: {filename}.")
            collection_name = f"{intent}_{COLLECTION_VERSION}"
            persist_dir = chroma_dir / collection_name
            marker = persist_dir / ".source_sha256"
            digest = _digest(pdf_path)
            store = None
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
                store = Chroma(
                    collection_name=collection_name,
                    embedding_function=embedder,
                    persist_directory=str(persist_dir),
                    collection_metadata={"hnsw:space": CHROMA_METRIC},
                )
                if store._collection.count() == 0:
                    store = None
            if store is None:
                if persist_dir.exists():
                    shutil.rmtree(persist_dir)
                chunks = build_chunks(intent, filename, title, docs_dir)
                store = Chroma.from_documents(
                    documents=chunks,
                    embedding=embedder,
                    collection_name=collection_name,
                    persist_directory=str(persist_dir),
                    collection_metadata={"hnsw:space": CHROMA_METRIC},
                )
                marker.write_text(digest, encoding="utf-8")
            stores[intent] = store
        return stores
    except KnowledgeBaseUnavailable:
        raise
    except Exception as exc:
        logger.error("Falha ao preparar base de conhecimento; tipo=%s", type(exc).__name__)
        raise KnowledgeBaseUnavailable("A base de conhecimento não está disponível.") from exc


def clean_legacy_collections(chroma_dir: Path) -> list[str]:
    removed: list[str] = []
    active = {f"{intent}_{COLLECTION_VERSION}" for intent in INTENTS}
    for folder in chroma_dir.iterdir() if chroma_dir.exists() else ():
        if folder.is_dir() and folder.name not in active and any(folder.name == name or folder.name.startswith(f"{name}_") for name in INTENTS):
            shutil.rmtree(folder)
            removed.append(folder.name)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara os índices RAG da Mila.")
    parser.add_argument("--clean-legacy", action="store_true", help="Remove índices antigos das intenções que não usam o esquema atual.")
    args = parser.parse_args()
    if args.clean_legacy:
        print("Coleções antigas removidas:", ", ".join(clean_legacy_collections(PROJECT_DIR / "dados" / "chroma")) or "nenhuma")
        return
    settings = Settings.model_construct(embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    stores = prepare_knowledge_bases(settings)
    print("Coleções prontas:", ", ".join(f"{name} ({store._collection.count()})" for name, store in stores.items()))


if __name__ == "__main__":
    main()

