/**
 * Browser sign-in for the provider-neutral OIDC backend.
 *
 * Authorization Code with PKCE, discovered from the issuer's well-known document,
 * so no client secret ever reaches the browser and no identity vendor is hardcoded.
 * The API verifies the resulting token against the issuer's JWKS; nothing here is
 * trusted by the server.
 */

export type AuthMode = "demo" | "oidc";

export const AUTH_MODE: AuthMode =
  (process.env.NEXT_PUBLIC_AUTH_MODE as AuthMode | undefined) ?? "demo";
const ISSUER = process.env.NEXT_PUBLIC_OIDC_ISSUER ?? "";
const CLIENT_ID = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "";
const SCOPE = process.env.NEXT_PUBLIC_OIDC_SCOPE ?? "openid profile email";

const VERIFIER_KEY = "gopilot.pkce_verifier";
const STATE_KEY = "gopilot.oidc_state";
const CALLBACK_PATH = "/auth/callback";

export function isOidcConfigured(): boolean {
  return AUTH_MODE === "oidc" && Boolean(ISSUER && CLIENT_ID);
}

function redirectUri(): string {
  return `${window.location.origin}${CALLBACK_PATH}`;
}

function base64UrlEncode(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function randomString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes.buffer);
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64UrlEncode(digest);
}

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}

let discoveryCache: Discovery | null = null;

async function discover(): Promise<Discovery> {
  if (discoveryCache) return discoveryCache;
  const base = ISSUER.replace(/\/+$/, "");
  const response = await fetch(`${base}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error(`Could not read the issuer's configuration (${response.status})`);
  }
  discoveryCache = (await response.json()) as Discovery;
  return discoveryCache;
}

/** Send the browser to the issuer to sign in. */
export async function beginSignIn(): Promise<void> {
  const { authorization_endpoint } = await discover();
  const verifier = randomString();
  const state = randomString(16);
  // sessionStorage, not localStorage: the verifier must not outlive the tab.
  window.sessionStorage.setItem(VERIFIER_KEY, verifier);
  window.sessionStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: redirectUri(),
    scope: SCOPE,
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${authorization_endpoint}?${params.toString()}`);
}

/**
 * Exchange the authorization code for tokens. Returns the access token.
 * Throws when `state` does not match, which is the CSRF check for this flow.
 */
export async function completeSignIn(search: string): Promise<string> {
  const params = new URLSearchParams(search);
  const error = params.get("error");
  if (error) {
    throw new Error(params.get("error_description") || `Sign-in failed: ${error}`);
  }
  const code = params.get("code");
  const state = params.get("state");
  const expectedState = window.sessionStorage.getItem(STATE_KEY);
  const verifier = window.sessionStorage.getItem(VERIFIER_KEY);
  window.sessionStorage.removeItem(STATE_KEY);
  window.sessionStorage.removeItem(VERIFIER_KEY);

  if (!code || !verifier) throw new Error("Sign-in response was incomplete");
  if (!state || state !== expectedState) {
    throw new Error("Sign-in state did not match; the response was discarded");
  }

  const { token_endpoint } = await discover();
  const response = await fetch(token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: CLIENT_ID,
      redirect_uri: redirectUri(),
      code_verifier: verifier,
    }).toString(),
  });
  if (!response.ok) {
    // Never surface the issuer's raw body; it can contain sensitive detail.
    throw new Error(`Token exchange failed (${response.status})`);
  }
  const payload = (await response.json()) as { access_token?: string };
  if (!payload.access_token) throw new Error("Issuer returned no access token");
  return payload.access_token;
}

export async function signOutUrl(): Promise<string | null> {
  try {
    const { end_session_endpoint } = await discover();
    return end_session_endpoint ?? null;
  } catch {
    return null;
  }
}
