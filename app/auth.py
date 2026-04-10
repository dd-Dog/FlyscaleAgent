import hmac

from fastapi import HTTPException, Request

from app.config import get_app_settings


def admin_login_configured() -> bool:
    s = get_app_settings()
    return bool(s.admin_user and s.admin_password)


def api_key_configured() -> bool:
    return bool(get_app_settings().api_key.strip())


def _extract_api_key_from_request(request: Request) -> str:
    provided = (request.headers.get("X-API-Key") or "").strip()
    if not provided:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    return provided


def verify_client_api_key(request: Request) -> None:
    s = get_app_settings()
    expected = s.api_key.strip()
    if not expected:
        return

    provided = _extract_api_key_from_request(request)

    if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def client_api_key_ok(provided: str | None) -> bool:
    """用于 WebSocket：query `api_key` 或传入的 header 值。"""
    s = get_app_settings()
    expected = s.api_key.strip()
    if not expected:
        return True
    p = (provided or "").strip()
    if not p:
        return False
    return hmac.compare_digest(p.encode("utf-8"), expected.encode("utf-8"))


def require_admin_session(request: Request) -> None:
    if not admin_login_configured():
        return
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="Not authenticated")


def validate_admin_credentials(username: str, password: str) -> bool:
    s = get_app_settings()
    if username != s.admin_user:
        return False
    return hmac.compare_digest(
        password.encode("utf-8"),
        s.admin_password.encode("utf-8"),
    )
