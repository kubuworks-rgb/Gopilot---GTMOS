"""A minimal OIDC issuer for local development and end-to-end tests.

**Never for production.** It authenticates nobody: you type a subject and it hands
you a token. It exists so the browser sign-in flow can be exercised end to end --
discovery, PKCE, code exchange, expiry, refresh, logout -- without provisioning a
real identity provider first, and so CI can test that flow without secrets.

It is a test double for an issuer, not an authentication system. GoPilot has no
password handling of its own and must not grow any: real deployments point
JWT_ISSUER at a real provider.

    python -m uvicorn services.dev_oidc.main:app --port 9000

Refuses to start when APP_ENV=production.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm


if os.getenv("APP_ENV") == "production":
    raise RuntimeError(
        "services.dev_oidc is a test issuer and must never run in production. "
        "Point JWT_ISSUER at a real OIDC provider."
    )

ISSUER = os.getenv("DEV_OIDC_ISSUER", "http://127.0.0.1:9000")
AUDIENCE = os.getenv("DEV_OIDC_AUDIENCE", "gopilot-local")
KEY_ID = "dev-oidc-key-1"
# Deliberately short so token expiry and refresh are exercised in normal use
# rather than only in a unit test.
ACCESS_TOKEN_TTL = int(os.getenv("DEV_OIDC_TTL_SECONDS", "900"))

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_jwk = json.loads(RSAAlgorithm.to_jwk(_private_key.public_key()))
_public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})


@dataclass
class PendingCode:
    subject: str
    email: str
    challenge: str
    redirect_uri: str
    created_at: float = field(default_factory=time.time)


@dataclass
class RefreshGrant:
    subject: str
    email: str


_codes: dict[str, PendingCode] = {}
_refresh: dict[str, RefreshGrant] = {}

app = FastAPI(title="GoPilot dev OIDC issuer", version="0.1.0")

# A browser-based PKCE client fetches discovery and the token endpoint directly, so
# a real issuer must serve CORS headers for them. Without these the flow fails with
# an opaque "Failed to fetch", which is exactly the kind of thing a test double
# should reproduce rather than paper over.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/.well-known/openid-configuration")
def discovery() -> JSONResponse:
    return JSONResponse(
        {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks.json",
            "end_session_endpoint": f"{ISSUER}/logout",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["openid", "profile", "email", "offline_access"],
        }
    )


@app.get("/jwks.json")
def jwks() -> JSONResponse:
    return JSONResponse({"keys": [_public_jwk]})


@app.get("/authorize", response_class=HTMLResponse)
def authorize(
    redirect_uri: str = Query(...),
    state: str = Query(""),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    client_id: str = Query(""),
    scope: str = Query(""),
) -> HTMLResponse:
    del client_id, scope
    if code_challenge_method != "S256":
        raise HTTPException(400, "Only S256 PKCE is supported")

    # A form, not a login: this issuer verifies nothing. It exists so the browser
    # flow can be driven with a chosen identity, including uninvited ones so the
    # private-alpha gate can be tested from the outside.
    return HTMLResponse(
        f"""<!doctype html><meta charset="utf-8">
<title>Dev OIDC — choose an identity</title>
<style>body{{font:15px system-ui;margin:0;display:grid;place-items:center;height:100vh;background:#0f1117;color:#e8ebf2}}
form{{background:#181b24;padding:28px;border-radius:12px;width:340px}}
h1{{font-size:16px;margin:0 0 4px}}p{{color:#8b93a7;font-size:12px;margin:0 0 18px}}
label{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8b93a7;margin:12px 0 4px}}
input{{width:100%;padding:9px;border-radius:7px;border:1px solid #2b3040;background:#0f1117;color:#e8ebf2;box-sizing:border-box}}
button{{width:100%;margin-top:18px;padding:10px;border:0;border-radius:7px;background:#3ddc84;color:#08210f;font-weight:700}}
small{{display:block;margin-top:14px;color:#6b7280}}</style>
<form method="post" action="/authorize">
<h1>Development sign-in</h1>
<p>Test issuer. It verifies nothing and must never run in production.</p>
<label>Subject</label><input name="subject" value="alpha-founder" required>
<label>Email</label><input name="email" value="founder@example.com" required>
<input type="hidden" name="redirect_uri" value="{redirect_uri}">
<input type="hidden" name="state" value="{state}">
<input type="hidden" name="code_challenge" value="{code_challenge}">
<button type="submit">Continue</button>
</form>"""
    )


@app.post("/authorize")
def authorize_submit(
    subject: str = Form(...),
    email: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(...),
) -> RedirectResponse:
    code = uuid.uuid4().hex
    _codes[code] = PendingCode(
        subject=subject.strip(),
        email=email.strip(),
        challenge=code_challenge,
        redirect_uri=redirect_uri,
    )
    query = urlencode({"code": code, "state": state})
    return RedirectResponse(f"{redirect_uri}?{query}", status_code=303)


def _issue(subject: str, email: str) -> dict[str, object]:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "email": email,
        "iat": now,
        "nbf": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    token = jwt.encode(
        claims, _private_key, algorithm="RS256", headers={"kid": KEY_ID}
    )
    refresh_token = uuid.uuid4().hex
    _refresh[refresh_token] = RefreshGrant(subject=subject, email=email)
    return {
        "access_token": token,
        "id_token": token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL,
    }


def _pkce_matches(verifier: str, challenge: str) -> bool:
    import base64

    digest = sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return expected == challenge


@app.post("/token")
def token(
    grant_type: str = Form(...),
    code: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
) -> JSONResponse:
    del client_id, redirect_uri

    if grant_type == "refresh_token":
        grant = _refresh.pop(refresh_token, None)
        if grant is None:
            raise HTTPException(400, "Unknown refresh token")
        return JSONResponse(_issue(grant.subject, grant.email))

    if grant_type != "authorization_code":
        raise HTTPException(400, f"Unsupported grant_type {grant_type}")

    pending = _codes.pop(code, None)
    if pending is None:
        raise HTTPException(400, "Unknown or already-used authorization code")
    if time.time() - pending.created_at > 300:
        raise HTTPException(400, "Authorization code expired")
    # PKCE is verified for real, so a broken client implementation fails here
    # rather than appearing to work.
    if not _pkce_matches(code_verifier, pending.challenge):
        raise HTTPException(400, "PKCE verification failed")

    return JSONResponse(_issue(pending.subject, pending.email))


@app.get("/logout")
def logout(post_logout_redirect_uri: str = Query("")) -> RedirectResponse:
    _refresh.clear()
    return RedirectResponse(post_logout_redirect_uri or "/", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "issuer": ISSUER, "note": "development issuer only"}
