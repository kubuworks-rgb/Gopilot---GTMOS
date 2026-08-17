import { clearSession, refreshAccessToken, tokenIsStale } from "./auth";
import type { Account, AccountImportRecord, AccountImportResult, AccountImportSource, AccountImportValidation, AccountReviewStatus, Bootstrap, Brief, BriefState, Campaign, Feedback, FeedbackRating, ICP, Product, ProductMode, ResearchRun, Workspace } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

/** One shape for validate and import, so the confirmed payload is the checked one. */
export interface ImportPayload {
  accounts?: AccountImportRecord[];
  pasted_domains?: string;
  csv_text?: string;
  import_source: AccountImportSource;
}

const ACCESS_TOKEN_KEY = "gopilot.access_token";

// sessionStorage is external state, so components read it through
// useSyncExternalStore rather than mirroring it into React state inside an
// effect, which would cause cascading renders and break under SSR.
const listeners = new Set<() => void>();

export function subscribeToAccessToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Store the verified access token for subsequent API calls. */
export function setAccessToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
  else window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  listeners.forEach((listener) => listener());
}

export function accessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
}

/** Server snapshot: the server never holds a browser token. */
export function serverAccessToken(): string | null {
  return null;
}

function authHeaders(): Record<string, string> {
  const token = accessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Raised when the session is gone and the caller should be sent to sign in. */
export class UnauthenticatedError extends Error {
  constructor(message = "Your session has ended. Please sign in again.") {
    super(message);
    this.name = "UnauthenticatedError";
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Refresh proactively when the token is about to expire, so a long session does
  // not fail mid-action and bounce the user out of work they were doing.
  if (tokenIsStale()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) setAccessToken(refreshed);
  }

  let response = await send(path, init);

  // A 401 after a valid-looking token usually means it expired early or the issuer
  // rotated keys. Try once, then give up rather than looping.
  if (response.status === 401 && accessToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      setAccessToken(refreshed);
      response = await send(path, init);
    }
  }

  if (response.status === 401) {
    setAccessToken(null);
    clearSession();
    throw new UnauthenticatedError();
  }

  if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/bootstrap"),
  createWorkspace: (name: string) =>
    request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name }) }),
  createProduct: (payload: { company_name: string; website: string; product: string; target_market: string }) =>
    request<Product>("/products", { method: "POST", body: JSON.stringify(payload) }),
  startResearch: (productId: string, productMode: ProductMode = "BYOA_CORE") =>
    request<ResearchRun>(`/research-runs?product_id=${encodeURIComponent(productId)}&product_mode=${productMode}`, { method: "POST" }),
  importSingle: (account: AccountImportRecord) =>
    request<AccountImportResult>("/accounts/import", { method: "POST", body: JSON.stringify({ accounts: [account], import_source: "SINGLE" }) }),
  importPasted: (pastedDomains: string) =>
    request<AccountImportResult>("/accounts/import", { method: "POST", body: JSON.stringify({ pasted_domains: pastedDomains, import_source: "PASTED_DOMAINS" }) }),
  importCsv: (csvText: string) =>
    request<AccountImportResult>("/accounts/import", { method: "POST", body: JSON.stringify({ csv_text: csvText, import_source: "CSV_UPLOAD" }) }),
  validateImport: (body: ImportPayload) =>
    request<AccountImportValidation>("/account-imports/validate", { method: "POST", body: JSON.stringify(body) }),
  importAccounts: (body: ImportPayload) =>
    request<AccountImportResult>("/accounts/import", { method: "POST", body: JSON.stringify(body) }),
  refreshAccounts: () => request<{ status: string }>("/accounts/refresh", { method: "POST" }),
  researchAccount: (accountId: string) =>
    request<{ status: string }>(`/accounts/${accountId}/research`, { method: "POST" }),
  regenerateBrief: (accountId: string) =>
    request<{ status: string }>(`/accounts/${accountId}/regenerate-brief`, { method: "POST" }),
  reviewAccount: (accountId: string, reviewStatus: AccountReviewStatus, briefState?: BriefState, note?: string) =>
    request<Account>(`/accounts/${accountId}/review`, { method: "PATCH", body: JSON.stringify({ review_status: reviewStatus, brief_state: briefState, note }) }),
  brief: (accountId: string) => request<Brief>(`/accounts/${accountId}/opportunity-brief`),
  selectICP: (icpId: string) =>
    request<ICP>(`/icps/${icpId}/select`, { method: "POST" }),
  campaign: (campaignId: string, payload: { action: "approve" | "reject" | "edit"; subject?: string; body?: string }) => request<Campaign>(`/campaigns/${campaignId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  feedback: (payload: { target_type: "account" | "signal" | "finding" | "brief"; target_id: string; rating: FeedbackRating; reason?: string; notes?: string }) =>
    request<Feedback>("/feedback", { method: "POST", body: JSON.stringify(payload) }),
};
