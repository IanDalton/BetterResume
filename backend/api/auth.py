"""Firebase ID token verification and admin gating.

The admin dashboard endpoints require a Firebase ID token whose verified email
matches ADMIN_EMAIL. Tokens are verified locally against Google's public
certificates (RS256) — no firebase-admin dependency needed.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request

logger = logging.getLogger("betterresume.auth")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "daltioan@gmail.com")

_GOOGLE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

# Simple module-level cert cache: {kid: cert_pem}, refreshed when expired
_cert_cache: Dict[str, str] = {}
_cert_cache_expiry: float = 0.0


def _fetch_google_certs() -> Dict[str, str]:
    """Fetch (and cache) Google's securetoken signing certificates."""
    global _cert_cache, _cert_cache_expiry
    now = time.time()
    if _cert_cache and now < _cert_cache_expiry:
        return _cert_cache
    resp = httpx.get(_GOOGLE_CERTS_URL, timeout=10.0)
    resp.raise_for_status()
    _cert_cache = resp.json()
    # Honor Cache-Control max-age when present; default to 1 hour
    max_age = 3600
    cache_control = resp.headers.get("cache-control", "")
    for part in cache_control.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                pass
    _cert_cache_expiry = now + max_age
    return _cert_cache


def verify_firebase_token(token: str) -> Dict[str, Any]:
    """Verify a Firebase ID token and return its claims.

    Raises ValueError on any verification failure.
    """
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    if not project_id:
        raise ValueError("FIREBASE_PROJECT_ID is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise ValueError(f"Malformed token: {e}")

    kid = header.get("kid")
    certs = _fetch_google_certs()
    cert_pem = certs.get(kid)
    if not cert_pem:
        raise ValueError("Unknown token key id")

    from cryptography.x509 import load_pem_x509_certificate

    public_key = load_pem_x509_certificate(cert_pem.encode("utf-8")).public_key()
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
        )
    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid token: {e}")
    return claims


async def require_admin(request: Request) -> Dict[str, Any]:
    """FastAPI dependency: only allow the configured admin (verified email)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header[len("Bearer "):].strip()

    try:
        claims = verify_firebase_token(token)
    except ValueError as e:
        logger.info("Admin auth failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    email = (claims.get("email") or "").lower()
    if email != ADMIN_EMAIL.lower() or not claims.get("email_verified", False):
        logger.warning("Admin access denied for email=%s", email or "<missing>")
        raise HTTPException(status_code=403, detail="Admin access required")

    logger.info("Admin access granted to %s", email)
    return claims
