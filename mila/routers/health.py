from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> dict[str, str]:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None or not runtime.settings.groq_api_key:
        raise HTTPException(status_code=503, detail="A Mila ainda não está pronta.")
    if set(runtime.vectorstores) != {"sobre_mindu", "cadastro", "agendamento", "empresa"}:
        raise HTTPException(status_code=503, detail="A Mila ainda não está pronta.")
    if any(store._collection.count() == 0 for store in runtime.vectorstores.values()):
        raise HTTPException(status_code=503, detail="A Mila ainda não está pronta.")
    return {"status": "ready"}

