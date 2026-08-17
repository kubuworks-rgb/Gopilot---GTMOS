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
const REFRESH_KEY = "gopilot.refresh_token";
const EXPIRY_KEY = "gopilot.token_expiry";
const RETURN_KEY = "gopilot.return_to";
const CALLBACK_PATH = "/auth/callback";
// Refresh a little before the token actually dies, so an in-flight request does
// not fail on a token that expired between the check and the call.
const REFRESH_MARGIN_MS = 60_000;

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
// An authorization code is single-use, and both the verifier and the code are
// consumed on the first attempt. React StrictMode invokes effects twice in
// development, and any remount would do the same in production, so a second
// attempt with the same code must return the first result rather than failing with
// "response was incomplete".
const inFlight = new Map<string, Promise<string>>();

export async function completeSignIn(search: string): Promise<string> {
  const params = new URLSearchParams(search);
  const code = params.get("code") ?? "";

  // The callback ran again after the exchange already finished — StrictMode's
  // second effect, a remount, or a back-navigation. The code and verifier are
  // gone by then, but we are signed in, so this is a success rather than the
  // "response was incomplete" error it used to produce.
  if (!code && !params.get("error")) {
    const existingToken = currentAccessToken();
    if (existingToken) return existingToken;
  }

  const existing = inFlight.get(code);
  if (code && existing) return existing;
  const attempt = exchangeAuthorizationCode(search);
  if (code) inFlight.set(code, attempt);
  return attempt;
}

/** Reads the stored token without importing the API module (avoids a cycle). */
function currentAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem("gopilot.access_token");
}

async function exchangeAuthorizationCode(search: string): Promise<string> {
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
  const payload = (await response.json()) as {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
  };
  if (!payload.access_token) throw new Error("Issuer returned no access token");
  storeSession({
    access_token: payload.access_token,
    refresh_token: payload.refresh_token,
    expires_in: payload.expires_in,
  });
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

/** Remember where the user was, so sign-in returns them there rather than home. */
export function rememberReturnPath(path: string): void {
  if (typeof window === "undefined") return;
  if (path.startsWith(CALLBACK_PATH)) return;
  window.sessionStorage.setItem(RETURN_KEY, path);
}

export function takeReturnPath(): string {
  if (typeof window === "undefined") return "/dashboard";
  const path = window.sessionStorage.getItem(RETURN_KEY);
  window.sessionStorage.removeItem(RETURN_KEY);
  return path && path.startsWith("/") ? path : "/dashboard";
}

export function storeSession(payload: {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
}): void {
  if (typeof window === "undefined") return;
  if (payload.refresh_token) {
    window.sessionStorage.setItem(REFRESH_KEY, payload.refresh_token);
  }
  if (payload.expires_in) {
    const expiry = Date.now() + payload.expires_in * 1000;
    window.sessionStorage.setItem(EXPIRY_KEY, String(expiry));
  }
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  for (const key of [REFRESH_KEY, EXPIRY_KEY, VERIFIER_KEY, STATE_KEY]) {
    window.sessionStorage.removeItem(key);
  }
}

function expiresAt(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(EXPIRY_KEY);
  return raw ? Number(raw) : null;
}

/** True when the stored token is expired or close enough that it will be. */
export function tokenIsStale(): boolean {
  const expiry = expiresAt();
  return expiry !== null && Date.now() >= expiry - REFRESH_MARGIN_MS;
}

/**
 * Exchange the refresh token for a new access token.
 *
 * Returns null when there is nothing to refresh with, or the issuer refuses — the
 * caller then sends the user back to sign-in rather than retrying forever.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const refreshToken = window.sessionStorage.getItem(REFRESH_KEY);
  if (!refreshToken || !CLIENT_ID) return null;
  try {
    const { token_endpoint } = await discover();
    const response = await fetch(token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: CLIENT_ID,
      }).toString(),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
    };
    if (!payload.access_token) return null;
    storeSession({
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      expires_in: payload.expires_in,
    });
    return payload.access_token;
  } catch {
    return null;
  }
}
