FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt

COPY mila ./mila
COPY documentos ./documentos
RUN python -c "from langchain_huggingface import HuggingFaceEmbeddings; HuggingFaceEmbeddings(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')" \
    && python -m mila.knowledge.ingest \
    && mkdir -p /app/dados/chroma

FROM base AS ui
COPY requirements-ui.txt .
RUN pip install --no-cache-dir -r requirements-ui.txt \
    && useradd --create-home --uid 10001 mila \
    && chown -R mila:mila /app /opt/hf-cache
COPY tools ./tools
USER mila
EXPOSE 8501
CMD ["streamlit", "run", "tools/ui.py", "--server.address", "0.0.0.0", "--server.port", "8501"]

FROM base AS api
RUN useradd --create-home --uid 10001 mila \
    && chown -R mila:mila /app /opt/hf-cache
USER mila
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10m --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["sh", "-c", "uvicorn mila.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
