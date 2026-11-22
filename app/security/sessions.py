import hmac
import re
from hashlib import sha256

from app.core.config import Settings

TOKEN_BYTES = 32
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def cookie_name(settings: Settings) -> str:
    return (
        "__Host-insightpilot_session"
        if settings.secure_session_cookie
        else "insightpilot_session"
    )


def session_digest(token: str) -> bytes:
    return sha256(token.encode("ascii")).digest()


def csrf_token(cookie: str) -> str:
    return hmac.digest(cookie.encode("ascii"), b"insightpilot-csrf-v1", "sha256").hex()
