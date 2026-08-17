"""Drive the whole OIDC browser flow end to end against a running stack.

Exercises what a browser does -- discovery, PKCE, code exchange, authenticated API
calls, refresh, and the invite gate -- so the flow is verified repeatably rather
than by clicking once.

Run the stack first:  npm run dev:oidc
Then:                 python scripts/verify_oidc_flow.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
import sys

import httpx


def check(condition: bool, label: str) -> bool:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return condition


def pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def sign_in(
    client: httpx.Client, issuer: str, redirect_uri: str, subject: str, email: str
) -> dict[str, object]:
    """Complete an authorization-code + PKCE sign-in, returning the token payload."""
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(16)

    authorized = client.post(
        f"{issuer}/authorize",
        data={
            "subject": subject,
            "email": email,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
        },
        follow_redirects=False,
    )
    location = authorized.headers["location"]
    returned_state = location.split("state=")[1].split("&")[0]
    assert returned_state == state, "issuer did not echo state back"
    code = location.split("code=")[1].split("&")[0]

    tokens = client.post(
        f"{issuer}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": "gopilot-local",
        },
    )
    tokens.raise_for_status()
    return tokens.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", default="http://127.0.0.1:9000")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--redirect", default="http://localhost:3000/auth/callback")
    parser.add_argument("--subject", default="alpha-founder")
    parser.add_argument("--uninvited", default="not-invited-person")
    args = parser.parse_args()

    failures = 0
    with httpx.Client(timeout=20) as client:
        print("\n[1] Discovery")
        # Send Origin so the response looks like a browser's: CORS headers are only
        # emitted for cross-origin requests, so omitting it tests nothing.
        discovery = client.get(
            f"{args.issuer}/.well-known/openid-configuration",
            headers={"Origin": "http://localhost:3000"},
        )
        doc = discovery.json()
        failures += not check(discovery.status_code == 200, "well-known document served")
        failures += not check(
            "S256" in doc.get("code_challenge_methods_supported", []),
            "PKCE S256 advertised",
        )
        failures += not check(
            bool(discovery.headers.get("access-control-allow-origin")),
            "CORS allows a browser client to read discovery",
        )

        print("\n[2] Signing keys")
        jwks = client.get(doc["jwks_uri"]).json()
        failures += not check(len(jwks.get("keys", [])) >= 1, "JWKS exposes a key")
        failures += not check(
            jwks["keys"][0].get("alg") == "RS256", "key is asymmetric RS256"
        )

        print("\n[3] Authorization code + PKCE")
        payload = sign_in(
            client, args.issuer, args.redirect, args.subject, "founder@example.com"
        )
        token = str(payload["access_token"])
        failures += not check(bool(token), "access token issued")
        failures += not check(
            bool(payload.get("refresh_token")), "refresh token issued"
        )
        failures += not check(
            int(payload.get("expires_in", 0)) > 0, "expiry advertised"
        )

        print("\n[4] PKCE is actually enforced")
        verifier, challenge = pkce()
        authorized = client.post(
            f"{args.issuer}/authorize",
            data={
                "subject": args.subject,
                "email": "founder@example.com",
                "redirect_uri": args.redirect,
                "state": "x",
                "code_challenge": challenge,
            },
            follow_redirects=False,
        )
        stolen_code = authorized.headers["location"].split("code=")[1].split("&")[0]
        wrong = client.post(
            f"{args.issuer}/token",
            data={
                "grant_type": "authorization_code",
                "code": stolen_code,
                "code_verifier": "not-the-right-verifier",
                "client_id": "gopilot-local",
            },
        )
        failures += not check(
            wrong.status_code == 400, "a stolen code without the verifier is refused"
        )

        print("\n[5] Authenticated API access")
        authed = client.get(
            f"{args.api}/bootstrap", headers={"Authorization": f"Bearer {token}"}
        )
        failures += not check(authed.status_code == 200, f"bootstrap authorised ({authed.status_code})")

        print("\n[6] Unauthenticated access is refused")
        for label, headers in [
            ("no header", {}),
            ("garbage token", {"Authorization": "Bearer not-a-jwt"}),
            ("wrong scheme", {"Authorization": f"Basic {token}"}),
        ]:
            response = client.get(f"{args.api}/bootstrap", headers=headers)
            failures += not check(
                response.status_code == 401, f"{label} rejected ({response.status_code})"
            )

        print("\n[7] Invite gate")
        uninvited = sign_in(
            client, args.issuer, args.redirect, args.uninvited, "stranger@example.com"
        )
        response = client.get(
            f"{args.api}/bootstrap",
            headers={"Authorization": f"Bearer {uninvited['access_token']}"},
        )
        failures += not check(
            response.status_code == 403,
            f"a validly-signed but uninvited identity is refused ({response.status_code})",
        )

        print("\n[8] Refresh")
        refreshed = client.post(
            f"{args.issuer}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": str(payload["refresh_token"]),
                "client_id": "gopilot-local",
            },
        )
        failures += not check(refreshed.status_code == 200, "refresh grant accepted")
        new_token = str(refreshed.json()["access_token"])
        still_ok = client.get(
            f"{args.api}/bootstrap", headers={"Authorization": f"Bearer {new_token}"}
        )
        failures += not check(
            still_ok.status_code == 200, "refreshed token authorises the API"
        )

        print("\n[9] A code cannot be replayed")
        replay = client.post(
            f"{args.issuer}/token",
            data={
                "grant_type": "authorization_code",
                "code": stolen_code,
                "code_verifier": verifier,
                "client_id": "gopilot-local",
            },
        )
        failures += not check(
            replay.status_code == 400, "an already-used code is refused"
        )

        print("\n[10] Tenant isolation")
        # A valid token is not a licence to read someone else's workspace: the
        # membership check has to run after the signature check, not instead of it.
        foreign = client.get(
            f"{args.api}/bootstrap",
            headers={
                "Authorization": f"Bearer {new_token}",
                "X-Workspace-Id": "00000000-0000-0000-0000-0000000000ff",
            },
        )
        failures += not check(
            foreign.status_code == 403,
            f"a valid token cannot reach another workspace ({foreign.status_code})",
        )

        print("\n[11] Logout")
        signed_out = client.get(
            f"{args.issuer}/logout",
            params={"post_logout_redirect_uri": "http://localhost:3000/"},
            follow_redirects=False,
        )
        failures += not check(
            signed_out.status_code in (302, 303),
            "logout redirects back to the application",
        )
        # The refresh token must not survive sign-out, or "log out" would only mean
        # "log out until the next background refresh".
        after_logout = client.post(
            f"{args.issuer}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": str(refreshed.json()["refresh_token"]),
                "client_id": "gopilot-local",
            },
        )
        failures += not check(
            after_logout.status_code == 400,
            f"the refresh token is dead after logout ({after_logout.status_code})",
        )

        print("\n[12] Signing back in")
        again = sign_in(
            client, args.issuer, args.redirect, args.subject, "founder@example.com"
        )
        resumed = client.get(
            f"{args.api}/bootstrap",
            headers={"Authorization": f"Bearer {again['access_token']}"},
        )
        failures += not check(
            resumed.status_code == 200, "a fresh sign-in authorises again"
        )
        failures += not check(
            resumed.json().get("workspace") is not None,
            "the workspace is still there after signing back in",
        )

    print(f"\n{'OIDC FLOW VERIFIED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
