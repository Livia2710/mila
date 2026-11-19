import hmac

from fastapi import Header, HTTPException, Request


def require_api_key(request: Request, x_mila_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.mila_api_key
    if not expected:
        return
    if x_mila_api_key is None or not hmac.compare_digest(x_mila_api_key.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Chave de API inválida.")

