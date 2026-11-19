import logging
from pathlib import Path
from typing import Any

from mila.config import Settings
from mila.prompts import MISSING_INFO_REPLY, RAG_SYSTEM_PROMPT
from mila.schemas import ChatResponse, ChatTurn
from mila.knowledge.store import retrieve
from mila.services.safety import is_short_followup

logger = logging.getLogger("mila.rag")


def _last_user_turn(history: list[ChatTurn]) -> str | None:
    for turn in reversed(history):
        if turn.role == "user":
            return turn.content
    return None


def _query(question: str, history: list[ChatTurn], settings: Settings, llm: Any) -> str:
    if not history or not settings.history_max_turns or not is_short_followup(question):
        return question
    previous = _last_user_turn(history)
    if not previous:
        return question
    if settings.rag_rewrite_followups:
        try:
            return llm.complete([
                {"role": "system", "content": "Reescreva a última mensagem como uma pergunta autônoma em português. Preserve a intenção. Responda apenas com a pergunta."},
                {"role": "user", "content": f"Pergunta anterior: {previous}\nMensagem atual: {question}"},
            ], temperature=0)
        except Exception:
            logger.info("Reescrita de continuação falhou; usando junção das perguntas")
    return f"{previous}\n{question}"


def answer_from_rag(question: str, history: list[ChatTurn], intent: str, runtime: Any) -> ChatResponse:
    query = _query(question, history, runtime.settings, runtime.llm)
    store = runtime.vectorstores[intent]
    try:
        selected_chunks = retrieve(
            store,
            query,
            top_k=runtime.settings.rag_top_k,
        )
    except Exception as exc:
        logger.error("Busca RAG falhou; intent=%s tipo=%s", intent, type(exc).__name__)
        from mila.errors import KnowledgeBaseUnavailable
        raise KnowledgeBaseUnavailable("A base de conhecimento não está disponível.") from exc
    candidates = [(chunk.document, chunk.relevance) for chunk in selected_chunks]
    selected = [(document, score) for document, score in candidates if score >= runtime.settings.rag_min_relevance]
    scores = [score for _, score in candidates]
    sources = sorted({Path(str(doc.metadata.get("source", ""))).name for doc, _ in selected if doc.metadata.get("source")})
    debug_info = {
        "similaridade_maxima": round(max(scores), 3) if scores else 0.0,
        "limite_configurado": runtime.settings.rag_min_relevance,
        "trechos_avaliados": [
            {"relevancia": round(score, 3), "fonte": Path(str(doc.metadata.get("source", ""))).name,
             "secao": doc.metadata.get("section", ""), "texto": doc.page_content}
            for doc, score in candidates
        ],
        "trechos_aceitos": len(selected),
    }
    if not selected:
        return ChatResponse(
            response=MISSING_INFO_REPLY,
            intent=intent,
            sources=sorted({Path(str(doc.metadata.get("source", ""))).name for doc, _ in candidates if doc.metadata.get("source")}),
            missing_info=True,
            debug_info=debug_info,
        )
    context = "\n\n---\n\n".join(document.page_content for document, _ in selected)
    recent_history = history[-runtime.settings.history_max_turns:] if runtime.settings.history_max_turns else []
    messages = [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        *[{"role": "user" if turn.role == "user" else "assistant", "content": turn.content[:1500]} for turn in recent_history],
        {"role": "user", "content": f"CONTEXTO DOS MATERIAIS:\n{context}\n\nPERGUNTA ATUAL:\n{question}"},
    ]
    response = runtime.llm.complete(messages)
    return ChatResponse(response=response, intent=intent, sources=sources, debug_info=debug_info)

