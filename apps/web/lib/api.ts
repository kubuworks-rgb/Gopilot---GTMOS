import type { Account, AccountImportRecord, AccountImportResult, AccountReviewStatus, Bootstrap, Brief, BriefState, Campaign, Feedback, FeedbackRating, ICP, Product, ProductMode, ResearchRun, Workspace } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
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
  refreshAccounts: () => request<{ status: string }>("/accounts/refresh", { method: "POST" }),
  researchAccount: (accountId: string) =>
    request<{ status: string }>(`/accounts/${accountId}/research`, { method: "POST" }),
  regenerateBrief: (accountId: string) =>
    request<{ status: string }>(`/accounts/${accountId}/regenerate-brief`, { method: "POST" }),
  reviewAccount: (accountId: string, reviewStatus: AccountReviewStatus, briefState?: BriefState) =>
    request<Account>(`/accounts/${accountId}/review`, { method: "PATCH", body: JSON.stringify({ review_status: reviewStatus, brief_state: briefState }) }),
  brief: (accountId: string) => request<Brief>(`/accounts/${accountId}/opportunity-brief`),
  selectICP: (icpId: string) =>
    request<ICP>(`/icps/${icpId}/select`, { method: "POST" }),
  campaign: (campaignId: string, payload: { action: "approve" | "reject" | "edit"; subject?: string; body?: string }) => request<Campaign>(`/campaigns/${campaignId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  feedback: (payload: { target_type: "account" | "signal" | "finding" | "brief"; target_id: string; rating: FeedbackRating; reason?: string; notes?: string }) =>
    request<Feedback>("/feedback", { method: "POST", body: JSON.stringify(payload) }),
};
