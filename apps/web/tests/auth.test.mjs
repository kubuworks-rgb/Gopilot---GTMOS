/**
 * Browser sign-in behaviour, asserted against lib/auth.ts itself.
 *
 * These cover the things that actually broke during the OIDC work rather than the
 * happy path: the StrictMode double-invoke that surfaced as "Sign-in response was
 * incomplete", the refresh margin, and the return-path handling that would be an
 * open redirect if it echoed back whatever it was given.
 *
 * Node strips the TypeScript types, so this exercises the shipped module — a
 * source-text check would pass against a version that does not work.
 */

import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

process.env.NEXT_PUBLIC_AUTH_MODE = "oidc";
process.env.NEXT_PUBLIC_OIDC_ISSUER = "http://127.0.0.1:9000";
process.env.NEXT_PUBLIC_OIDC_CLIENT_ID = "gopilot-local";

function memoryStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    clear: () => map.clear(),
    get size() {
      return map.size;
    },
  };
}

const storage = memoryStorage();
globalThis.window = {
  sessionStorage: storage,
  location: { origin: "http://localhost:3000" },
};

const DISCOVERY = {
  authorization_endpoint: "http://127.0.0.1:9000/authorize",
  token_endpoint: "http://127.0.0.1:9000/token",
  end_session_endpoint: "http://127.0.0.1:9000/logout",
};

let tokenExchanges = 0;
globalThis.fetch = async (url) => {
  if (String(url).includes(".well-known")) {
    return { ok: true, json: async () => DISCOVERY };
  }
  tokenExchanges += 1;
  return {
    ok: true,
    json: async () => ({
      access_token: `token-${tokenExchanges}`,
      refresh_token: "refresh-abc",
      expires_in: 900,
    }),
  };
};

const auth = await import("../lib/auth.ts");

// The in-flight map that makes the exchange idempotent is keyed by authorization
// code and lives for the module's lifetime, so each test uses a distinct code.
beforeEach(() => {
  storage.clear();
  tokenExchanges = 0;
});

test("a completed sign-in stores the refresh token and an expiry", async () => {
  storage.setItem("gopilot.oidc_state", "state-1");
  storage.setItem("gopilot.pkce_verifier", "verifier-1");

  const token = await auth.completeSignIn("?code=abc&state=state-1");

  assert.equal(token, "token-1");
  assert.equal(storage.getItem("gopilot.refresh_token"), "refresh-abc");
  assert.ok(Number(storage.getItem("gopilot.token_expiry")) > Date.now());
});

test("the second StrictMode invocation does not fail after the code is consumed", async () => {
  // The real sequence: the effect runs, the exchange succeeds, replaceState strips
  // the code, then the effect runs again with an empty query. That used to throw
  // "Sign-in response was incomplete" over a session that was in fact valid.
  storage.setItem("gopilot.oidc_state", "state-1");
  storage.setItem("gopilot.pkce_verifier", "verifier-1");
  await auth.completeSignIn("?code=strictmode&state=state-1");
  storage.setItem("gopilot.access_token", "token-1");

  const second = await auth.completeSignIn("");

  assert.equal(second, "token-1");
  assert.equal(tokenExchanges, 1, "the code must not be exchanged twice");
});

test("concurrent callbacks with the same code share one exchange", async () => {
  storage.setItem("gopilot.oidc_state", "state-1");
  storage.setItem("gopilot.pkce_verifier", "verifier-1");

  const [a, b] = await Promise.all([
    auth.completeSignIn("?code=shared&state=state-1"),
    auth.completeSignIn("?code=shared&state=state-1"),
  ]);

  assert.equal(a, b);
  assert.equal(tokenExchanges, 1);
});

test("a mismatched state is rejected as a forged callback", async () => {
  storage.setItem("gopilot.oidc_state", "state-1");
  storage.setItem("gopilot.pkce_verifier", "verifier-1");

  await assert.rejects(
    () => auth.completeSignIn("?code=forged&state=attacker-state"),
    /state did not match/,
  );
});

test("an issuer error is surfaced, not swallowed into a blank session", async () => {
  await assert.rejects(
    () => auth.completeSignIn("?error=access_denied&error_description=Denied"),
    /Denied/,
  );
});

test("a token is stale before it expires, not after", () => {
  storage.setItem("gopilot.token_expiry", String(Date.now() + 5 * 60_000));
  assert.equal(auth.tokenIsStale(), false);

  // Inside the refresh margin: still valid, but a request starting now could
  // outlive it, so it must refresh first.
  storage.setItem("gopilot.token_expiry", String(Date.now() + 30_000));
  assert.equal(auth.tokenIsStale(), true);

  storage.setItem("gopilot.token_expiry", String(Date.now() - 1));
  assert.equal(auth.tokenIsStale(), true);
});

test("no expiry means nothing to refresh rather than permanently stale", () => {
  assert.equal(auth.tokenIsStale(), false);
});

test("refresh exchanges the stored refresh token and restores the session", async () => {
  storage.setItem("gopilot.refresh_token", "refresh-abc");

  const token = await auth.refreshAccessToken();

  assert.equal(token, "token-1");
  assert.ok(Number(storage.getItem("gopilot.token_expiry")) > Date.now());
});

test("refresh returns null when there is nothing to refresh with", async () => {
  assert.equal(await auth.refreshAccessToken(), null);
  assert.equal(tokenExchanges, 0);
});

test("a refused refresh returns null so the caller signs in again", async () => {
  storage.setItem("gopilot.refresh_token", "revoked-after-logout");
  const original = globalThis.fetch;
  globalThis.fetch = async (url) =>
    String(url).includes(".well-known")
      ? { ok: true, json: async () => DISCOVERY }
      : { ok: false, status: 400, json: async () => ({}) };

  assert.equal(await auth.refreshAccessToken(), null);
  globalThis.fetch = original;
});

test("signing out clears the refresh token and the expiry", () => {
  storage.setItem("gopilot.refresh_token", "refresh-abc");
  storage.setItem("gopilot.token_expiry", String(Date.now() + 900_000));

  auth.clearSession();

  assert.equal(storage.getItem("gopilot.refresh_token"), null);
  assert.equal(storage.getItem("gopilot.token_expiry"), null);
});

test("the return path is remembered and consumed exactly once", () => {
  auth.rememberReturnPath("/accounts");

  assert.equal(auth.takeReturnPath(), "/accounts");
  assert.equal(auth.takeReturnPath(), "/dashboard", "it must not replay");
});

test("the callback is never remembered as a return path", () => {
  auth.rememberReturnPath("/auth/callback?code=abc");

  assert.equal(auth.takeReturnPath(), "/dashboard");
});

test("an absolute URL is not accepted as a return path", () => {
  // Otherwise sign-in becomes an open redirect: land on the attacker's page
  // carrying the trust of having just authenticated.
  auth.rememberReturnPath("https://evil.example/steal");

  assert.equal(auth.takeReturnPath(), "/dashboard");
});
