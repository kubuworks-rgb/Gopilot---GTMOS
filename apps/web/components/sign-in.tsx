"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { setAccessToken } from "@/lib/api";
import { AUTH_MODE, beginSignIn, completeSignIn, isOidcConfigured } from "@/lib/auth";

/** Shown when OIDC is configured and the browser holds no access token. */
export function SignIn() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start() {
    setBusy(true);
    setError("");
    try {
      await beginSignIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in could not start");
      setBusy(false);
    }
  }

  return (
    <main className="loading-screen">
      <div className="brand-mark">G</div>
      <span className="demo-badge">PRIVATE ALPHA · INVITE ONLY</span>
      <h1>Sign in to GoPilot</h1>
      <p>
        This deployment is invite-only. Sign in with the identity provider your
        workspace was invited through.
      </p>
      {error && <p className="hypothesis-note">{error}</p>}
      {!isOidcConfigured() ? (
        <p className="hypothesis-note">
          Sign-in is not configured. Set NEXT_PUBLIC_OIDC_ISSUER and
          NEXT_PUBLIC_OIDC_CLIENT_ID, then rebuild the web image.
        </p>
      ) : (
        <button className="primary-button large" disabled={busy} onClick={() => void start()}>
          {busy ? "Redirecting…" : "Sign in →"}
        </button>
      )}
      <p className="hypothesis-note">
        GoPilot never sends outreach on your behalf. Every status change stays
        human-approved.
      </p>
    </main>
  );
}

/** Handles the issuer's redirect back to /auth/callback. */
export function AuthCallback({ onSignedIn }: { onSignedIn: () => void }) {
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    completeSignIn(window.location.search)
      .then((token) => {
        if (cancelled) return;
        setAccessToken(token);
        // Drop the code and state from the address bar before continuing.
        window.history.replaceState({}, "", "/dashboard");
        onSignedIn();
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Sign-in failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onSignedIn]);

  if (error) {
    return (
      <main className="loading-screen error">
        <div className="brand-mark">!</div>
        <h1>Sign-in failed</h1>
        <p>{error}</p>
        <Link className="primary-button" href="/">
          Try again
        </Link>
      </main>
    );
  }

  return (
    <main className="loading-screen">
      <div className="brand-mark">G</div>
      <h1>Completing sign-in…</h1>
      <p>Verifying your identity with the issuer.</p>
    </main>
  );
}

export function signOut(): void {
  setAccessToken(null);
  window.location.assign("/");
}

export const authModeIsOidc = AUTH_MODE === "oidc";
