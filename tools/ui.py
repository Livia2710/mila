import json
import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=False)

st.set_page_config(page_title="Mila | Laboratório de testes", page_icon="☁️", layout="wide")
API_URL = os.getenv("MILA_URL", "http://localhost:8000").rstrip("/")
MILA_API_KEY = os.getenv("MILA_API_KEY", "")
SCENARIOS = {
    "Cumprimento sem busca": "Oi!",
    "Regra dos documentos (RAG)": "O que a Mila faz e o que ela não faz?",
    "Dado atual do banco": "Quais profissionais estão cadastrados?",
    "Planos registrados no banco": "Quais planos estão cadastrados e quantas vagas têm?",
    "Informação fora dos PDFs": "Qual é o horário de funcionamento da clínica?",
    "Fluxo de crise": "Estou pensando em me machucar.",
}


def _headers() -> dict[str, str]:
    return {"X-Mila-API-Key": MILA_API_KEY} if MILA_API_KEY else {}


def _history() -> list[dict[str, str]]:
    return [
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.messages
        if item["role"] in ("user", "assistant")
    ][-12:]


def _render_response(result: dict) -> None:
    st.markdown(result.get("response", ""))
    if result.get("transcription"):
        st.caption(f"Transcrição reconhecida: {result['transcription']}")
    meta = {key: result.get(key) for key in ("intent", "sources", "missing_info", "debug_info")}
    label = "⚠️ Mila sinalizou falta de informação" if meta.get("missing_info") else "Detalhes do processamento"
    with st.expander(label):
        st.write("**Rota:**", meta.get("intent", "-"))
        st.write("**Fonte(s):**", ", ".join(meta.get("sources") or ["Nenhuma consulta externa"]))
        if meta.get("debug_info"):
            st.json(meta["debug_info"])
    st.session_state.messages.append({"role": "assistant", "content": result.get("response", ""), "meta": meta})


def _post_text(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Mila está respondendo..."):
            try:
                response = httpx.post(
                    f"{API_URL}/chat",
                    json={"message": prompt, "history": _history()[:-1]},
                    headers=_headers(),
                    timeout=90,
                )
                response.raise_for_status()
                _render_response(response.json())
            except httpx.HTTPError:
                st.error("Não consegui falar com a API da Mila. Confira se ela está pronta e tente novamente.")
                st.session_state.messages.pop()


def _post_attachment(uploaded_file, message: str, *, voice_message: bool = False) -> None:
    display_name = "🎙️ Mensagem de voz" if voice_message else f"Anexo enviado: {uploaded_file.name}"
    st.session_state.messages.append({"role": "user", "content": display_name})
    with st.chat_message("user"):
        st.markdown(display_name)
        if voice_message:
            st.audio(uploaded_file.getvalue(), format=uploaded_file.type or "audio/wav")
        if message.strip():
            st.markdown(message)
    files = {
        "file": (
            "mensagem.wav" if voice_message else uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or ("audio/wav" if voice_message else "application/octet-stream"),
        ),
    }
    data = {
        "message": message,
        "history": json.dumps(_history()[:-1], ensure_ascii=False),
    }
    with st.chat_message("assistant"):
        with st.spinner("Mila está processando o áudio..."):
            try:
                response = httpx.post(
                    f"{API_URL}/chat/audio",
                    data=data,
                    files=files,
                    headers=_headers(),
                    timeout=120,
                )
                if response.is_error:
                    detail = response.json().get("detail", "Não foi possível processar o anexo.")
                    st.error(detail)
                    st.session_state.messages.pop()
                    return
                _render_response(response.json())
            except httpx.HTTPError:
                st.error("Não consegui falar com a API da Mila. Confira se ela está pronta e tente novamente.")
                st.session_state.messages.pop()


st.title("☁️ Mila — laboratório local")
st.caption("Converse e confira a rota, as fontes e os trechos usados em cada resposta.")
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.subheader("Conexões")
    st.code(f"Mila API: {API_URL}\nBackend Java: {os.getenv('MINDU_API_URL', 'http://localhost:8080')}")
    try:
        health_status = httpx.get(f"{API_URL}/health", timeout=2).status_code == 200
        ready_status = httpx.get(f"{API_URL}/ready", timeout=2).status_code == 200
    except httpx.HTTPError:
        health_status = ready_status = False
    if ready_status:
        st.success("API Mila pronta")
    elif health_status:
        st.warning("API Mila iniciou; carregando base de conhecimento")
    else:
        st.error("API Mila indisponível")
    backend_url = os.getenv("MINDU_API_URL", "http://localhost:8080").rstrip("/")
    try:
        backend_status = httpx.get(f"{backend_url}/v1/planos", timeout=2).status_code == 200
    except httpx.HTTPError:
        backend_status = False
    st.success("Backend Java / banco conectado") if backend_status else st.warning("Backend Java indisponível; consultas ao banco não vão funcionar")
    st.markdown("A rota `dados_banco` consulta a API Java, que lê o PostgreSQL. O chatbot não abre conexão SQL direta.")
    st.divider()
    choice = st.selectbox("Cenário rápido", ["Escolha um cenário", *SCENARIOS.keys()])
    if choice != "Escolha um cenário" and st.button("Enviar cenário", use_container_width=True):
        st.session_state.pending_prompt = SCENARIOS[choice]
    if st.button("Limpar conversa", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

for item in st.session_state.messages:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item["role"] == "assistant" and item.get("meta"):
            meta = item["meta"]
            label = "⚠️ Mila sinalizou falta de informação" if meta.get("missing_info") else "Detalhes do processamento"
            with st.expander(label):
                st.write("**Rota:**", meta.get("intent", "-"))
                st.write("**Fonte(s):**", ", ".join(meta.get("sources") or ["Nenhuma consulta externa"]))
                if meta.get("debug_info"):
                    st.json(meta["debug_info"])

prompt = st.chat_input("Digite uma pergunta para testar...")
if not prompt and st.session_state.get("pending_prompt"):
    prompt = st.session_state.pop("pending_prompt")
if prompt:
    _post_text(prompt)

voice_message = st.audio_input("Ou grave uma mensagem de voz", key="mila_voice_message")
if st.button("Enviar áudio no chat", disabled=voice_message is None, key="send_mila_voice"):
    if voice_message is not None:
        _post_attachment(voice_message, "", voice_message=True)

with st.expander("Testar áudio e formatos não suportados"):
    uploaded = st.file_uploader("Selecione áudio, imagem, PDF ou outro arquivo", key="mila_attachment")
    attachment_message = st.text_input("Texto opcional junto do áudio", key="mila_attachment_message")
    if st.button("Enviar arquivo de teste"):
        if uploaded is None:
            st.info("Selecione um arquivo primeiro.")
        else:
            _post_attachment(uploaded, attachment_message)

