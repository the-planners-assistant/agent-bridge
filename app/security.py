"""Security helpers for HMAC and Bearer auth.

The new API spec introduces bearerAuth. For development we allow either:
  - HMAC: x-signature header containing sha256(secret, raw_body)
  - Bearer: Authorization: Bearer <token>

If AUTH_OPTIONAL is True (default for local dev), absence of both is permitted.
"""

import hmac, hashlib
from fastapi import HTTPException, Request
from .settings import settings

def _verify_hmac(raw_body: bytes, signature: str) -> bool:
    digest = hmac.new(settings.HMAC_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)

def _verify_bearer(auth_header: str) -> bool:
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[len("Bearer "):].strip()
    if settings.BEARER_TOKEN is None:
        # Accept any bearer in dev if token not configured
        return True
    return hmac.compare_digest(token, settings.BEARER_TOKEN)

def require_auth(req: Request, raw_body: bytes) -> None:
    """Enforce auth according to settings.

    Order of checks:
      1. Bearer Authorization if present.
      2. x-signature HMAC if present.
      3. If neither and AUTH_OPTIONAL is False -> 401.
    """
    authz = req.headers.get("authorization") or req.headers.get("Authorization")
    sig = req.headers.get("x-signature") or req.headers.get("X-Signature")

    if authz and _verify_bearer(authz):
        return
    if sig and _verify_hmac(raw_body, sig):
        return
    if settings.AUTH_OPTIONAL:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")
