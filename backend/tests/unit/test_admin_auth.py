"""Tests for Firebase token verification and the admin-only dependency."""

import datetime

import jwt as pyjwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import api.auth as auth_module
from api.auth import require_admin, verify_firebase_token

PROJECT_ID = "test-project"
ADMIN = "daltioan@gmail.com"


@pytest.fixture(scope="module")
def signing_material():
    """Self-signed cert + private key emulating Google's securetoken certs."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return key_pem, cert_pem


def _make_token(key_pem, email=ADMIN, email_verified=True, project=PROJECT_ID, kid="kid-1", **overrides):
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "aud": project,
        "iss": f"https://securetoken.google.com/{project}",
        "iat": now,
        "exp": now + datetime.timedelta(hours=1),
        "sub": "uid123",
        "email": email,
        "email_verified": email_verified,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, key_pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def configured(monkeypatch, signing_material):
    key_pem, cert_pem = signing_material
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT_ID)
    monkeypatch.setattr(auth_module, "ADMIN_EMAIL", ADMIN)
    monkeypatch.setattr(auth_module, "_fetch_google_certs", lambda: {"kid-1": cert_pem})
    return key_pem


# ---------------------------------------------------------------------------
# verify_firebase_token
# ---------------------------------------------------------------------------

def test_valid_token_returns_claims(configured):
    token = _make_token(configured)
    claims = verify_firebase_token(token)
    assert claims["email"] == ADMIN
    assert claims["email_verified"] is True


def test_expired_token_rejected(configured):
    now = datetime.datetime.now(datetime.timezone.utc)
    token = _make_token(configured, exp=now - datetime.timedelta(hours=1))
    with pytest.raises(ValueError, match="Invalid token"):
        verify_firebase_token(token)


def test_wrong_audience_rejected(configured):
    token = _make_token(configured, project=PROJECT_ID, aud="other-project")
    with pytest.raises(ValueError, match="Invalid token"):
        verify_firebase_token(token)


def test_unknown_kid_rejected(configured):
    token = _make_token(configured, kid="unknown-kid")
    with pytest.raises(ValueError, match="Unknown token key id"):
        verify_firebase_token(token)


def test_garbage_token_rejected(configured):
    with pytest.raises(ValueError, match="Malformed token"):
        verify_firebase_token("not-a-jwt")


def test_missing_project_id_rejected(monkeypatch, signing_material):
    key_pem, _ = signing_material
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    with pytest.raises(ValueError, match="FIREBASE_PROJECT_ID"):
        verify_firebase_token(_make_token(key_pem))


# ---------------------------------------------------------------------------
# require_admin dependency (via a minimal FastAPI app)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/protected")
    async def protected(claims: dict = Depends(require_admin)):
        return {"email": claims.get("email")}

    return TestClient(app)


def test_missing_header_401(client):
    assert client.get("/protected").status_code == 401


def test_invalid_token_401(client, configured):
    resp = client.get("/protected", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_wrong_email_403(client, configured):
    token = _make_token(configured, email="intruder@example.com")
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_unverified_email_403(client, configured):
    token = _make_token(configured, email_verified=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_admin_email_allowed(client, configured):
    token = _make_token(configured)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == ADMIN


def test_admin_email_case_insensitive(client, configured):
    token = _make_token(configured, email="Daltioan@Gmail.com")
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
