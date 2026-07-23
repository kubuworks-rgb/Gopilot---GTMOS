import type { Bootstrap, Brief, Campaign, ICP } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

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
  brief: (accountId: string) => request<Brief>(`/accounts/${accountId}/opportunity-brief`),
  selectICP: (icpId: string) =>
    request<ICP>(`/icps/${icpId}/select`, { method: "POST" }),
  campaign: (campaignId: string, payload: { action: "approve" | "reject" | "edit"; subject?: string; body?: string }) => request<Campaign>(`/campaigns/${campaignId}`, { method: "PATCH", body: JSON.stringify(payload) }),
};
