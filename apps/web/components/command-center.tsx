"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { accessToken, api, API_BASE, serverAccessToken, subscribeToAccessToken, UnauthenticatedError, type ImportPayload } from "@/lib/api";
import { isOidcConfigured, rememberReturnPath } from "@/lib/auth";
import type { Account, AccountImportResult, AccountImportValidation, AccountReviewStatus, Bootstrap, Brief, BriefState, Evidence, EvidenceClaim, FeedbackRating, ImportRowVerdict, ResearchRun, RetrievalOutcome } from "@/lib/types";
import { EMPTY_FILTERS, SCORE_THRESHOLDS, facetValues, filterAccounts, isFiltered, tagValues, type AccountFilters, type SortKey } from "@/lib/account-filters";
import { EvidenceDrawer } from "./evidence-drawer";
import { ScoreBadge, ScoreDetails } from "./score";
import { AuthCallback, SignIn, signOut } from "./sign-in";

const nav = [
  ["dashboard", "Command center", "⌘"], ["import", "Import accounts", "⇧"],
  ["accounts", "Review priorities", "▤"], ["product", "Product profile", "◈"],
  ["research", "Research", "⌕"], ["icps", "ICP studio", "◎"],
  ["discovery", "Experimental discovery", "✧"], ["campaigns", "Campaigns", "✦"],
  ["approvals", "Approvals", "✓"], ["settings", "Settings", "⚙"],
] as const;

function Loading() { return <main className="loading-screen"><div className="brand-mark">K</div><h1>Preparing your intelligence workspace</h1><p>Loading evidence, scores, and workflow state…</p></main>; }
function ErrorState({ message, retry, setup }: { message: string; retry: () => void; setup: () => void }) { return <main className="loading-screen error"><div className="brand-mark">!</div><h1>Workspace setup needed</h1><p>{message}</p><code>{API_BASE}</code><div className="hero-actions"><button className="primary-button" onClick={setup}>Create live workspace</button><button className="secondary-button" onClick={retry}>Try again</button></div></main>; }

function EvidenceLink({ claim, brief, open }: { claim: EvidenceClaim; brief: Brief; open: (item: Evidence) => void }) {
  const item = brief.evidence.find(ev => claim.evidence_ids.includes(ev.id));
  return <article className="claim-card"><div><span className={`status-pill ${claim.status}`}>{claim.status.replace("_", " ")}</span><h3>{claim.statement}</h3><p>{Math.round(claim.confidence * 100)}% confidence</p></div>{item ? <button className="evidence-button" onClick={() => open(item)}>View evidence <span>↗</span></button> : <span className="hypothesis-note">Discovery hypothesis</span>}</article>;
}

export function CommandCenter({ segments }: { segments: string[] }) {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [campaignBusy, setCampaignBusy] = useState(false);
  const [icpBusy, setIcpBusy] = useState("");
  const [actionBusy, setActionBusy] = useState("");
  const [importResult, setImportResult] = useState<AccountImportResult | null>(null);
  const [importValidation, setImportValidation] = useState<AccountImportValidation | null>(null);
  const [pendingImport, setPendingImport] = useState<ImportPayload | null>(null);
  const view = segments[0] ?? "home";
  const accountId = view === "accounts" ? segments[1] : undefined;
  const researchStatus = data?.research_run?.status;
  const isCallback = view === "auth" && segments[1] === "callback";

  // The token lives in sessionStorage, which is external state. Reading it through
  // useSyncExternalStore keeps SSR correct and avoids mirroring it into React state.
  const token = useSyncExternalStore(subscribeToAccessToken, accessToken, serverAccessToken);
  // A configured OIDC deployment must not call the API before a token exists,
  // or every request 401s and the user sees an error instead of a way to sign in.
  const signedIn = !isOidcConfigured() || Boolean(token);

  // Remember the destination so sign-in returns the user here, not to the dashboard.
  useEffect(() => {
    if (!signedIn && isOidcConfigured() && !isCallback) {
      rememberReturnPath(window.location.pathname);
    }
  }, [signedIn, isCallback]);

  useEffect(() => {
    if (isCallback || !signedIn) return;
    api.bootstrap().then(setData).catch(err => {
      // An expired session mid-session must show the sign-in screen, not an error
      // the user cannot act on.
      if (err instanceof UnauthenticatedError) {
        rememberReturnPath(window.location.pathname);
        setData(null);
        return;
      }
      setError(err instanceof Error ? err.message : "Unknown API error");
    });
  }, [refresh, isCallback, signedIn]);
  useEffect(() => { if (accountId) api.brief(accountId).then(setBrief).catch(err => setError(err instanceof Error ? err.message : "Could not load account")); }, [accountId]);
  useEffect(() => {
    if (!researchStatus || !["queued", "planning", "researching", "extracting", "discovering_accounts", "scoring"].includes(researchStatus)) return;
    const timer = window.setInterval(() => setRefresh(value => value + 1), 3000);
    return () => window.clearInterval(timer);
  }, [researchStatus]);

  const averagePriority = useMemo(() => data?.accounts.length ? Math.round(data.accounts.reduce((sum, item) => sum + item.scores.priority, 0) / data.accounts.length) : 0, [data]);
  if (isCallback) return <AuthCallback onSignedIn={() => setRefresh(value => value + 1)} />;
  if (!signedIn) return <SignIn />;
  if (error) return <ErrorState message={error} setup={() => { setActionBusy("workspace"); api.createWorkspace("GoPilot Live Workspace").then(() => { setError(""); setRefresh(value => value + 1); }).catch(err => setError(err instanceof Error ? err.message : "Workspace creation failed")).finally(() => setActionBusy("")); }} retry={() => { setError(""); setRefresh(value => value + 1); }} />;
  if (!data) return <Loading />;
  if (data.mode === "live" && !data.product) return <LiveOnboarding busy={actionBusy} onSubmit={async payload => { setActionBusy("product"); try { await api.createProduct(payload); setData(await api.bootstrap()); } finally { setActionBusy(""); } }} />;

  if (view === "home") return <Marketing data={data} />;

  async function campaignAction(action: "approve" | "reject" | "edit", subject?: string, body?: string) {
    if (!brief) return;
    setCampaignBusy(true);
    try { const campaign = await api.campaign(brief.campaign.id, { action, subject, body }); setBrief({ ...brief, campaign }); setData(await api.bootstrap()); }
    finally { setCampaignBusy(false); }
  }

  async function selectICP(icpId: string) {
    setIcpBusy(icpId);
    try {
      await api.selectICP(icpId);
      setData(await api.bootstrap());
    } finally {
      setIcpBusy("");
    }
  }

  async function startResearch() {
    if (!data?.product) return;
    setActionBusy("research");
    try {
      await api.startResearch(data.product.id, "BYOA_CORE");
      setData(await api.bootstrap());
    } finally {
      setActionBusy("");
    }
  }

  function importPayload(kind: "single" | "pasted" | "csv", value: { company_name: string; domain: string } | string) {
    if (kind === "single") return { accounts: [value as { company_name: string; domain: string }], import_source: "SINGLE" as const };
    if (kind === "pasted") return { pasted_domains: value as string, import_source: "PASTED_DOMAINS" as const };
    return { csv_text: value as string, import_source: "CSV_UPLOAD" as const };
  }

  // Blueprint section 8: validate and show the per-row outcome before anything is
  // written, so the user inspects duplicates and problems before research starts.
  async function validateImport(kind: "single" | "pasted" | "csv", value: { company_name: string; domain: string } | string) {
    setActionBusy("import");
    setImportResult(null);
    try {
      const payload = importPayload(kind, value);
      setPendingImport(payload);
      setImportValidation(await api.validateImport(payload));
    } finally {
      setActionBusy("");
    }
  }

  async function confirmImport() {
    const current = data;
    if (!current?.product || !pendingImport) return;
    setActionBusy("import");
    try {
      if (!current.research_run || current.research_run.product_mode !== "BYOA_CORE") {
        await api.startResearch(current.product.id, "BYOA_CORE");
      }
      setImportResult(await api.importAccounts(pendingImport));
      setImportValidation(null);
      setPendingImport(null);
      setData(await api.bootstrap());
    } finally {
      setActionBusy("");
    }
  }

  async function startExperimentalDiscovery() {
    const current = data;
    if (!current?.product || !current.mode_availability.search_provider_configured) return;
    setActionBusy("discovery");
    try {
      await api.startResearch(current.product.id, "AUTONOMOUS_DISCOVERY_EXPERIMENTAL");
      setData(await api.bootstrap());
    } finally {
      setActionBusy("");
    }
  }

  const title = view === "accounts" && accountId ? brief?.account.name ?? "Account brief" : nav.find(item => item[0] === view)?.[1] ?? "Command center";
  return <div className="app-shell">
    <aside className="sidebar"><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><div className="workspace-switch"><span>Workspace</span><strong>{data.workspace.name}</strong><small>Founder workspace · Owner</small></div><nav aria-label="Primary">{nav.map(([slug, label, icon]) => <Link key={slug} href={`/${slug}`} className={`${view === slug ? "active" : ""} ${slug === "discovery" ? "experimental-nav" : ""}`}><span>{icon}</span>{label}{slug === "discovery" && <small>EXPERIMENTAL</small>}{slug === "approvals" && data.approval_count > 0 && <b>{data.approval_count}</b>}</Link>)}</nav><div className="sidebar-footer"><span className="status-dot" /> BYOA core available<small>{data.provider_message}</small>{isOidcConfigured() && <button className="secondary-button" onClick={() => void signOut()}>Sign out</button>}</div></aside>
    <main className="workspace"><header className="topbar"><div><span className="eyebrow">{view === "accounts" && accountId ? "Account opportunity brief" : "Evidence-backed GTM workspace"}</span><h1>{title}</h1></div><div className="top-actions"><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span><span className="avatar">KW</span></div></header>
      <div className="content">
        {view === "dashboard" && <Dashboard data={data} averagePriority={averagePriority} />}
        {view === "import" && <ImportAccountsView busy={actionBusy === "import"} result={importResult} validation={importValidation} onValidate={validateImport} onConfirm={() => void confirmImport()} onCancel={() => { setImportValidation(null); setPendingImport(null); }} />}
        {view === "product" && <ProductView data={data} busy={actionBusy === "research"} onResearch={startResearch} />}
        {view === "research" && <ResearchView data={data} />}
        {view === "icps" && <ICPView data={data} busyId={icpBusy} onSelect={selectICP} />}
        {view === "discovery" && <ExperimentalDiscoveryView data={data} busy={actionBusy === "discovery"} onStart={startExperimentalDiscovery} />}
        {view === "accounts" && !accountId && <AccountsView data={data} />}
        {view === "accounts" && accountId && brief && <><div className="top-actions"><button className="secondary-button" disabled={Boolean(actionBusy)} onClick={() => { setActionBusy("account"); void api.researchAccount(brief.account.id).finally(() => setActionBusy("")); }}>Research account</button><button className="secondary-button" disabled={Boolean(actionBusy)} onClick={() => { setActionBusy("brief"); void api.regenerateBrief(brief.account.id).finally(() => setActionBusy("")); }}>Regenerate brief</button></div><BriefView brief={brief} openEvidence={setEvidence} campaignBusy={campaignBusy} campaignAction={campaignAction} /></>}
        {view === "campaigns" && <CampaignsView data={data} />}
        {view === "approvals" && <ApprovalsView data={data} />}
        {view === "settings" && <SettingsView data={data} />}
        {(view === "login" || view === "onboarding") && <Onboarding data={data} />}
      </div>
    </main>{evidence && brief && <EvidenceDrawer evidence={evidence} sources={brief.sources} onClose={() => setEvidence(null)} />}
  </div>;
}

function LiveOnboarding({ busy, onSubmit }: { busy: string; onSubmit: (payload: { company_name: string; website: string; product: string; target_market: string }) => Promise<void> }) {
  const [company, setCompany] = useState("");
  const [website, setWebsite] = useState("https://");
  const [product, setProduct] = useState("");
  const [target, setTarget] = useState("");
  return <main className="loading-screen"><div className="brand-mark">G</div><span className="demo-badge">LIVE RESEARCH</span><h1>Confirm your product profile</h1><p>These inputs are stored as user-confirmed facts. Public research begins only when you start a run.</p><form className="onboarding-card" onSubmit={event => { event.preventDefault(); void onSubmit({ company_name: company, website, product, target_market: target }); }}><label>Company<input required minLength={2} value={company} onChange={event => setCompany(event.target.value)} /></label><label>Website<input required type="url" value={website} onChange={event => setWebsite(event.target.value)} /></label><label>Product<textarea required minLength={5} value={product} onChange={event => setProduct(event.target.value)} /></label><label>Target market<textarea required minLength={5} value={target} onChange={event => setTarget(event.target.value)} /></label><button disabled={Boolean(busy)} className="primary-button" type="submit">{busy ? "Saving…" : "Save confirmed profile"}</button></form></main>;
}

function Marketing({ data }: { data: Bootstrap }) {
  if (data.mode === "live") return <main className="marketing"><nav><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><Link className="primary-button" href="/import">Import accounts</Link></nav><section className="hero"><span className="demo-badge">BYOA CORE · LIVE PUBLIC DATA</span><h1>Research the accounts you already care about.</h1><p>Import company domains, verify official evidence, review deterministic priorities, and keep every status change human-approved. No search provider is required.</p><div className="hero-actions"><Link className="primary-button large" href="/import">Import accounts →</Link><Link className="secondary-button large" href="/discovery">Experimental discovery</Link></div></section></main>;
  return <main className="marketing"><nav><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><div><a href="#principles">How it works</a><Link className="primary-button" href="/dashboard">Open demo workspace</Link></div></nav><section className="hero"><span className="demo-badge">DETERMINISTIC PRODUCT DEMO</span><h1>Know exactly <em>who</em> to approach—and <em>why now.</em></h1><p>Turn your market into a ranked set of defensible account opportunities. Every claim opens to its source. Every score explains its math. Every action stays human-approved.</p><div className="hero-actions"><Link className="primary-button large" href="/dashboard">Explore the command center →</Link><Link className="secondary-button large" href="/accounts">View ranked accounts</Link></div><div className="proof-row"><span>✓ Evidence-linked claims</span><span>✓ Deterministic scores</span><span>✓ Human approval</span><span>✓ No autonomous outreach</span></div></section><section className="preview"><div className="preview-header"><span><i /> GoPilot Command Center</span><span className="demo-badge">DEMO DATA</span></div><div className="preview-grid"><div><small>Ranked opportunities</small><strong>{data.accounts.length}</strong><p>Fixture accounts ready for review</p></div>{data.accounts.slice(0,2).map(account => <article key={account.id}><span>{account.industry}</span><h3>{account.name}</h3><p>{account.top_signal}</p><b>{account.scores.priority}<small>Priority</small></b></article>)}</div></section><section id="principles" className="principles"><span className="eyebrow">A different unit of value</span><h2>Not another lead scraper.</h2><div><article><b>01</b><h3>Inspect the evidence</h3><p>Material claims connect to an observed passage and original source metadata.</p></article><article><b>02</b><h3>Understand the score</h3><p>Fit and intent stay separate, confidence gates priority, and the math remains deterministic.</p></article><article><b>03</b><h3>Keep humans in control</h3><p>Drafts can be edited, approved, or rejected. The MVP never auto-sends outreach.</p></article></div></section></main>;
}

const ACTIVE_RUN_STATUSES = ["queued", "planning", "researching", "extracting", "awaiting_icp", "discovering_accounts", "scoring"];

/** Short enough for the metric tile, which is sized for numbers, not sentences. */
function runLabel(run: ResearchRun | null, active: boolean): string {
  if (!run) return "None";
  if (active) return "Running";
  return { completed: "Done", partial: "Partial", failed: "Failed" }[run.status] ?? run.status;
}

/**
 * Reports what actually happened. Every figure here is derived from the run and
 * the accounts; nothing is asserted. The previous version hardcoded "Research is
 * complete", an active-run count of 1, "All above confidence threshold" and five
 * ticked workflow steps regardless of state, which is precisely the kind of
 * unearned claim the rest of the product refuses to make.
 */
function Dashboard({ data, averagePriority }: { data: Bootstrap; averagePriority: number }) {
  const run = data.research_run;
  const runActive = Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
  const researched = data.accounts.filter(item => item.domain_validation !== "CANONICALIZED_UNVERIFIED");
  const awaitingResearch = data.accounts.length - researched.length;
  const withSignal = data.accounts.filter(item => item.scores.intent.score > 0);
  const founderReady = data.accounts.filter(item => item.brief_state === "FOUNDER_READY");
  const needsReview = data.accounts.filter(item => item.brief_state === "IDENTITY_REVIEW_REQUIRED");

  const headline = !data.accounts.length
    ? "No accounts imported yet."
    : awaitingResearch > 0
      ? `${awaitingResearch} of ${data.accounts.length} accounts still awaiting official-source research.`
      : founderReady.length > 0
        ? `${founderReady.length} of ${data.accounts.length} accounts are evidence-gated founder ready.`
        : `${data.accounts.length} accounts researched; none has met the founder-ready evidence gate yet.`;

  const steps: [string, boolean, string][] = [
    ["Product profile confirmed", Boolean(data.product), data.product ? "User-confirmed input" : "Not yet provided"],
    ["Accounts imported", data.accounts.length > 0, data.accounts.length ? `${data.accounts.length} imported` : "None yet"],
    ["Official sources researched", researched.length > 0, researched.length ? `${researched.length} researched` : "Not started"],
    ["Deterministic scores calculated", researched.length > 0, researched.length ? "Fit, intent and confidence" : "Awaiting research"],
    ["Human review", data.accounts.some(item => item.review_status !== "PENDING"), "Approval is always required"],
  ];

  return <><section className="intro-row"><div><h2>Workspace status</h2><p>{headline}</p></div><Link className="primary-button" href={data.accounts.length ? "/accounts" : "/import"}>{data.accounts.length ? "Review priorities →" : "Import accounts →"}</Link></section>
    <section className="metric-grid">
      <div><span>Research run</span><strong>{runLabel(run, runActive)}</strong><small>{run ? `${run.documents_used} documents · ${run.searches_used} searches` : "Import accounts to begin"}</small></div>
      <div><span>Accounts</span><strong>{data.accounts.length}</strong><small>{awaitingResearch > 0 ? `${awaitingResearch} awaiting research` : "All researched"}</small></div>
      <div><span>Average priority</span><strong>{averagePriority}</strong><small>Confidence-adjusted, deterministic</small></div>
      <div><span>Needs approval</span><strong>{data.approval_count}</strong><small>Drafts, never auto-sent</small></div>
    </section>
    {needsReview.length > 0 && <section className="section-card"><span className="eyebrow">Attention</span><h2>{needsReview.length} account{needsReview.length === 1 ? "" : "s"} need identity review</h2><p>Their supplied domains could not be verified against official sources.</p></section>}
    <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Ranked by defensibility</span><h2>Top account opportunities</h2></div><Link href="/accounts">View all accounts →</Link></div><AccountTable accounts={data.accounts} compact /></section>
    <section className="dashboard-bottom">
      <div className="section-card workflow-card"><div className="section-heading"><div><span className="eyebrow">Workflow</span><h2>Progress</h2></div><span className={`status-pill ${runActive ? "partially_supported" : run ? "supported" : ""}`}>{run ? (runActive ? "in progress" : run.status) : "not started"}</span></div>{steps.map(([label, done, detail]) => <div className="workflow-step" key={label}><span>{done ? "✓" : "○"}</span><div><strong>{label}</strong><small>{detail}</small></div></div>)}</div>
      <div className="section-card signal-card"><div className="section-heading"><div><span className="eyebrow">Verified current signals</span><h2>Why now</h2></div></div>{withSignal.length ? withSignal.map(account => <Link href={`/accounts/${account.id}`} key={account.id}><span>↗</span><div><strong>{account.name}</strong><p>{account.top_signal}</p></div><small>{account.scores.intent.score} intent</small></Link>) : <p>No account has a verified current signal. NO_SIGNAL is a valid result — monitoring remains the correct action.</p>}</div>
    </section></>;
}

function ImportAccountsView({ busy, result, validation, onValidate, onConfirm, onCancel }: { busy: boolean; result: AccountImportResult | null; validation: AccountImportValidation | null; onValidate: (kind: "single" | "pasted" | "csv", value: { company_name: string; domain: string } | string) => Promise<void>; onConfirm: () => void; onCancel: () => void }) {
  const [method, setMethod] = useState<"single" | "pasted" | "csv">("single");
  const [company, setCompany] = useState("");
  const [domain, setDomain] = useState("");
  const [bulk, setBulk] = useState("");
  const onImport = onValidate;
  return <section className="import-workflow">
    <div className="workflow-strip">{["Import Accounts", "Validate Accounts", "Research Accounts", "Review Priorities", "Inspect Briefs", "Approve or Change Status", "Export"].map((item, index) => <span className={index === 0 ? "active" : ""} key={item}>{index + 1}. {item}</span>)}</div>
    <div className="section-card import-card">
      <div><span className="eyebrow">BYOA core · default mode</span><h2>Import accounts you already care about</h2><p>Account research uses supplied official domains and remains available without Exa or Tavily.</p></div>
      <div className="import-tabs">{(["single", "pasted", "csv"] as const).map(item => <button className={method === item ? "active" : ""} key={item} onClick={() => setMethod(item)}>{item === "single" ? "Single account" : item === "pasted" ? "Pasted domains" : "CSV upload"}</button>)}</div>
      {method === "single" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("single", { company_name: company, domain }); }}><label>Company name<input required minLength={2} value={company} onChange={event => setCompany(event.target.value)} placeholder="Acme Software" /></label><label>Official domain<input required value={domain} onChange={event => setDomain(event.target.value)} placeholder="acme.com" /></label><button className="primary-button" disabled={busy} type="submit">{busy ? "Checking…" : "Check accounts"}</button></form>}
      {method === "pasted" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("pasted", bulk); }}><label>One domain per line<textarea required rows={10} value={bulk} onChange={event => setBulk(event.target.value)} placeholder={"Acme, acme.com\nexample.org"} /></label><button className="primary-button" disabled={busy} type="submit">{busy ? "Checking…" : "Check accounts"}</button></form>}
      {method === "csv" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("csv", bulk); }}><label>CSV file<input required type="file" accept=".csv,text/csv" onChange={event => { const file = event.target.files?.[0]; if (file) void file.text().then(setBulk); }} /></label><small>Required headers: company_name, domain. Optional: industry, country, employee_band, notes, crm_id, owner, tags.</small><button className="primary-button" disabled={busy || !bulk} type="submit">{busy ? "Checking…" : "Check accounts"}</button></form>}
      {validation && <ImportValidationReport validation={validation} busy={busy} onConfirm={onConfirm} onCancel={onCancel} />}
      {result && <div className="import-result"><strong>{result.imported.length} accounts imported</strong><span>{result.duplicate_domains.length} duplicates skipped</span>{result.issues.map((issue, index) => <small key={`${issue.code}-${index}`}>Row {issue.row}: {issue.message}</small>)}{result.imported.length > 0 && <Link className="primary-button" href="/accounts">Research imported accounts →</Link>}</div>}
    </div>
  </section>;
}

const VERDICT_LABELS: Record<ImportRowVerdict, string> = {
  VALID: "Valid",
  DUPLICATE: "Duplicate",
  INVALID: "Invalid",
  NEEDS_REVIEW: "Needs review",
};

/**
 * Blueprint section 8: show what happened to every submitted row before research
 * starts. Every row appears, including accepted ones, so nothing can be silently
 * dropped between upload and research.
 */
function ImportValidationReport({ validation, busy, onConfirm, onCancel }: { validation: AccountImportValidation; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  const { summary, rows } = validation;
  const problems = rows.filter(item => item.verdict !== "VALID");
  const canonicalised = rows.filter(item => item.canonical_domain && item.submitted_domain && item.submitted_domain.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "") !== item.canonical_domain);
  return <div className="import-result">
    <strong>{summary.total} row{summary.total === 1 ? "" : "s"} checked</strong>
    <span>{summary.valid} valid · {summary.duplicate} duplicate · {summary.invalid} invalid · {summary.needs_review} need review</span>
    {canonicalised.length > 0 && <small>{canonicalised.length} domain{canonicalised.length === 1 ? " was" : "s were"} canonicalised: {canonicalised.slice(0, 5).map(item => `${item.submitted_domain} → ${item.canonical_domain}`).join(", ")}{canonicalised.length > 5 ? ", …" : ""}</small>}
    {problems.length > 0 && <div className="table-wrap"><table><thead><tr><th>Row</th><th>Company</th><th>Domain</th><th>Result</th><th>Reason</th></tr></thead><tbody>
      {problems.map(item => <tr key={item.row}>
        <td>{item.row}</td>
        <td>{item.company_name ?? "—"}</td>
        <td>{item.canonical_domain ?? item.submitted_domain ?? "—"}</td>
        <td><span className={`qualification-pill ${item.verdict.toLowerCase()}`}>{VERDICT_LABELS[item.verdict]}</span></td>
        <td>{item.reason ?? "—"}</td>
      </tr>)}
    </tbody></table></div>}
    {summary.valid + summary.needs_review === 0
      ? <><p>Nothing here can be imported. Fix the rows above and try again.</p><button className="secondary-button" onClick={onCancel}>Start over</button></>
      : <footer><button className="primary-button" disabled={busy} onClick={onConfirm}>{busy ? "Importing…" : `Import ${summary.valid + summary.needs_review} account${summary.valid + summary.needs_review === 1 ? "" : "s"}`}</button><button className="secondary-button" disabled={busy} onClick={onCancel}>Cancel</button></footer>}
  </div>;
}

function ExperimentalDiscoveryView({ data, busy, onStart }: { data: Bootstrap; busy: boolean; onStart: () => Promise<void> }) {
  const available = data.mode_availability.autonomous_discovery_experimental === "AVAILABLE";
  return <section className="section-card experimental-card"><span className="demo-badge">EXPERIMENTAL</span><h2>Automatic account discovery</h2><p>This secondary workflow may surface useful research candidates, but every result requires human review and must not be treated as founder-ready by default.</p><div className="warning-callout"><strong>Human review required</strong><span>{data.provider_message}</span></div><dl className="definition-list"><div><dt>Status</dt><dd>{available ? "Provider configured" : "Configuration required"}</dd></div><div><dt>Core account research</dt><dd>Available</dd></div><div><dt>Production promise</dt><dd>Experimental candidates only</dd></div></dl><button className="primary-button" disabled={busy || !available} onClick={() => void onStart()}>{busy ? "Queueing…" : available ? "Start experimental discovery" : "Search provider configuration required"}</button></section>;
}

function ProductView({ data, busy, onResearch }: { data: Bootstrap; busy: boolean; onResearch: () => Promise<void> }) { const p = data.product; if (!p) return null; return <section className="two-column"><div className="section-card profile-card"><span className="eyebrow">Confirmed product profile</span><h2>{p.company_name}</h2><a href={p.website}>{p.website}</a><label>Product</label><p>{p.product}</p><label>Target market</label><p>{p.target_market}</p><label>Structured understanding</label><div className="profile-claims">{p.understanding.map(claim => <div key={claim.field}><span>{claim.field.replaceAll("_", " ")}</span><strong>{claim.value ?? "Unknown"}</strong><small className={`provenance ${claim.status.toLowerCase()}`}>{claim.status.replaceAll("_", " ")}</small></div>)}</div><div className="callout"><span>◈</span><div><strong>Evidence vs inference</strong><p>Company inputs are user-confirmed. Market conclusions remain separately evidence-linked.</p></div></div></div><div className="section-card"><span className="eyebrow">Profile status</span><h2>Ready for research</h2><dl className="definition-list"><div><dt>Status</dt><dd><span className="status-pill supported">confirmed</span></dd></div><div><dt>Research mode</dt><dd>{data.mode === "live" ? "Live public sources" : "Fixture provider"}</dd></div><div><dt>Current run</dt><dd>{data.research_run?.status ?? "Not started"}</dd></div></dl><button className="primary-button" disabled={busy} onClick={() => void onResearch()}>{busy ? "Queueing…" : data.research_run ? "Run fresh research" : "Start live research"}</button></div></section>; }

function ResearchView({ data }: { data: Bootstrap }) { const run = data.research_run; if (!run) return <section className="section-card"><h2>No research run yet</h2><p>Confirm the product profile, then start a bounded research run.</p></section>; return <><section className="research-hero"><div><span className="status-pill supported">{run.status}</span><h2>{data.product_mode === "BYOA_CORE" ? "Official-source research" : "Market and ICP discovery"}</h2><p>Run {run.id} · {data.mode === "live" ? "live public-source research" : "deterministic fixture research"}</p></div><div><strong>{run.documents_used}</strong><span>documents</span><strong>{run.searches_used}</strong><span>searches</span></div></section>{!run.findings.length && <section className="section-card"><span className="eyebrow">Market findings</span><h2>None recorded</h2><p>{data.product_mode === "BYOA_CORE" ? "Imported-account research verifies the companies you supplied; it does not produce market-level findings. Per-account results are on each account's brief." : "No market findings were extracted for this run."}</p></section>}<section className="finding-grid">{run.findings.map(item => <article className="finding-card" key={item.id}><div><span className="category-icon">{item.category === "market" ? "↗" : item.category === "competitor" ? "◫" : item.category === "pain_point" ? "!" : "✦"}</span><span className="eyebrow">{item.category.replace("_", " ")}</span></div><h3>{item.claim}</h3><footer><span className={`status-pill ${item.status}`}>{item.status.replace("_", " ")}</span><span>{Math.round(item.confidence * 100)}% confidence</span><span>{item.evidence_ids.length} evidence</span></footer></article>)}</section><section className="section-card budget-card"><div><span className="eyebrow">Run budget</span><h2>Bounded by policy</h2><p>Optional source failure returns partial results; it cannot crash the full workflow.</p></div><div><label>Searches <b>{run.searches_used}{run.max_searches ? `/${run.max_searches}` : ""}</b></label>{run.max_searches ? <progress value={run.searches_used} max={run.max_searches} /> : null}<label>Documents <b>{run.documents_used}{run.max_documents ? `/${run.max_documents}` : ""}</b></label>{run.max_documents ? <progress value={run.documents_used} max={run.max_documents} /> : null}</div></section></>; }

function ICPView({ data, busyId, onSelect }: { data: Bootstrap; busyId: string; onSelect: (icpId: string) => Promise<void> }) { return <><section className="intro-row"><div><span className="eyebrow">{data.icps.length === 1 ? "Active profile" : `${data.icps.length} candidates`}</span><h2>{data.product_mode === "BYOA_CORE" ? "Target profile for your imported accounts" : "Choose the market worth learning from"}</h2><p>{data.product_mode === "BYOA_CORE" ? "You supplied the accounts, so this profile records what qualifies them rather than selecting a market." : "Each candidate traces its rationale to research evidence."}</p></div></section><section className="icp-grid">{data.icps.map((icp, index) => <article className={`icp-card ${icp.selected ? "selected" : ""}`} key={icp.id}><header><span>ICP 0{index + 1}</span><span>{icp.recommended && <b>★ Recommended</b>}{icp.selected && <b>✓ Selected</b>}</span></header><h2>{icp.name}</h2><p>{icp.description}</p><label>Firmographics</label><div className="tag-list">{icp.firmographics.map(item => <span key={item}>{item}</span>)}</div><label>Qualification logic</label><ul>{icp.qualification_logic.map(item => <li key={item}>{item}</li>)}</ul><label>Buying triggers</label><ul>{icp.triggers.map(item => <li key={item}>{item}</li>)}</ul><footer><span>{icp.evidence_ids.length === 0 ? "User-confirmed, not evidence-derived" : `${icp.evidence_ids.length} evidence record${icp.evidence_ids.length === 1 ? "" : "s"}`}</span><button disabled={icp.selected || Boolean(busyId)} onClick={() => void onSelect(icp.id)}>{icp.selected ? "Active ICP" : busyId === icp.id ? "Selecting…" : "Select ICP"}</button></footer></article>)}</section></>; }

function AccountTable({ accounts, compact = false }: { accounts: Account[]; compact?: boolean }) {
  const data = { accounts };
  return <div className="table-wrap"><table><thead><tr><th>Company</th><th>Provenance</th><th>Status</th><th>Fit</th><th>Intent</th><th>Confidence</th><th>Priority</th><th>Top signal</th><th /></tr></thead><tbody>{data.accounts.slice(0, compact ? 3 : undefined).map(account => <tr key={account.id}><td><div className="company-cell"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><strong>{account.name}</strong><small>{account.domain} · {account.location}</small></div></div></td><td><span className={`provenance-badge ${account.provenance.toLowerCase()}`}>{account.provenance}</span><small className="cell-note">{account.import_source?.replaceAll("_", " ") ?? "AUTONOMOUS DISCOVERY"}</small></td><td><span className={`qualification-pill ${account.brief_state.toLowerCase()}`}>{account.brief_state.replaceAll("_", " ")}</span><small className="cell-note">{account.review_status.replaceAll("_", " ")}</small></td><td><b>{account.scores.fit.score}</b></td><td><b>{account.scores.intent.score}</b></td><td><b>{account.scores.confidence.score}</b></td><td><span className="priority-pill">{account.priority_band} · {account.scores.priority}</span></td><td><p className="signal-text">{account.top_signal_type && <strong>{account.top_signal_type.replaceAll("_", " ")} · </strong>}{account.top_signal}</p></td><td><Link className="row-link" href={`/accounts/${account.id}`}>Inspect →</Link></td></tr>)}</tbody></table></div>;
}
const SORT_LABELS: Record<SortKey, string> = {
  priority: "Priority",
  fit: "Fit",
  intent: "Intent",
  confidence: "Confidence",
  unknowns: "Fewest unknowns",
};

const SCORE_FILTERS = [
  { key: "minPriority", label: "Priority" },
  { key: "minFit", label: "Fit" },
  { key: "minIntent", label: "Intent" },
  { key: "minConfidence", label: "Confidence" },
] as const satisfies readonly { key: keyof AccountFilters; label: string }[];

/**
 * Blueprint §14. These controls previously rendered and did nothing. Facet options
 * are derived from the accounts actually present, so the list never offers a filter
 * that would return zero rows.
 */
function AccountsView({ data }: { data: Bootstrap }) {
  const [filters, setFilters] = useState<AccountFilters>(EMPTY_FILTERS);
  const visible = useMemo(() => filterAccounts(data.accounts, filters), [data.accounts, filters]);
  const set = (patch: Partial<AccountFilters>) => setFilters(current => ({ ...current, ...patch }));

  const states = facetValues(data.accounts, "brief_state");
  const industries = facetValues(data.accounts, "industry");
  const countries = facetValues(data.accounts, "location");
  const owners = facetValues(data.accounts, "owner");
  const tags = tagValues(data.accounts);

  return <>
    <section className="filter-bar">
      <input aria-label="Search accounts" placeholder="⌕  Search accounts…" value={filters.search} onChange={event => set({ search: event.target.value })} />
      <select aria-label="State" value={filters.state} onChange={event => set({ state: event.target.value })}><option value="">All states</option>{states.map(item => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select>
      {industries.length > 0 && <select aria-label="Industry" value={filters.industry} onChange={event => set({ industry: event.target.value })}><option value="">All industries</option>{industries.map(item => <option key={item} value={item}>{item}</option>)}</select>}
      {countries.length > 0 && <select aria-label="Country" value={filters.country} onChange={event => set({ country: event.target.value })}><option value="">All countries</option>{countries.map(item => <option key={item} value={item}>{item}</option>)}</select>}
      {owners.length > 0 && <select aria-label="Owner" value={filters.owner} onChange={event => set({ owner: event.target.value })}><option value="">All owners</option>{owners.map(item => <option key={item} value={item}>{item}</option>)}</select>}
      {tags.length > 0 && <select aria-label="Tag" value={filters.tag} onChange={event => set({ tag: event.target.value })}><option value="">All tags</option>{tags.map(item => <option key={item} value={item}>{item}</option>)}</select>}
      <select aria-label="Signal" value={filters.signal} onChange={event => set({ signal: event.target.value as AccountFilters["signal"] })}><option value="">Any signal</option><option value="with">Has a signal</option><option value="without">No signal</option></select>
      {SCORE_FILTERS.map(({ key, label }) => <select key={key} aria-label={label} value={filters[key]} onChange={event => set({ [key]: Number(event.target.value) } as Partial<AccountFilters>)}>
        <option value={0}>Any {label.toLowerCase()}</option>
        {SCORE_THRESHOLDS.map(threshold => <option key={threshold} value={threshold}>{label} {threshold}+</option>)}
      </select>)}
      <select aria-label="Unknowns" value={filters.unknowns} onChange={event => set({ unknowns: event.target.value as AccountFilters["unknowns"] })}><option value="">Any unknowns</option><option value="without">Nothing unresolved</option><option value="with">Has open questions</option></select>
      <select aria-label="Sort by" value={filters.sort} onChange={event => set({ sort: event.target.value as SortKey })}>{(Object.keys(SORT_LABELS) as SortKey[]).map(key => <option key={key} value={key}>Sort: {SORT_LABELS[key]}</option>)}</select>
      <span>{isFiltered(filters) ? `${visible.length} of ${data.accounts.length} accounts` : `${data.accounts.length} accounts`}</span>
      {isFiltered(filters) && <button onClick={() => setFilters({ ...EMPTY_FILTERS, sort: filters.sort })}>Clear filters</button>}
      <Link className="primary-button" href="/import">Import accounts</Link>
    </section>
    <section className="section-card account-table-card">
      {visible.length === 0
        ? <p>{data.accounts.length === 0 ? "No accounts imported yet." : "No account matches these filters."}</p>
        : <AccountTable accounts={visible} />}
    </section>
  </>;
}

const RETRIEVAL_LABELS: Record<RetrievalOutcome, string> = {
  RETRIEVED: "Read",
  TRUNCATED: "Read in part (page exceeded the size limit)",
  NOT_FOUND: "Not present on this site",
  FORBIDDEN: "Access refused by the site",
  UNAVAILABLE: "Could not be reached",
  TIMED_OUT: "Timed out",
  RATE_LIMITED: "Rate limited by the site",
  BLOCKED_BY_POLICY: "Blocked by the safety policy",
  UNSUPPORTED_CONTENT: "Not a readable document",
  CROSS_DOMAIN_REDIRECT: "Redirected off the company domain",
};

/**
 * What the research actually managed to read. Without this a brief built from one
 * page out of eight was indistinguishable from one built from all eight, and the
 * failures -- which the gateway distinguishes into nine outcomes -- were visible
 * nowhere in the product.
 */
function RetrievalPanel({ retrieval }: { retrieval: Brief["retrieval"] }) {
  if (!retrieval || !retrieval.attempted) return null;
  // Absent pages are not failures: most company sites have no /careers page.
  const absent = retrieval.attempts.filter(item => item.outcome === "NOT_FOUND");
  const failed = retrieval.attempts.filter(item => !["RETRIEVED", "TRUNCATED", "NOT_FOUND"].includes(item.outcome));
  const existing = retrieval.attempted - absent.length;
  const coverage = existing > 0 ? Math.round((retrieval.retrieved / existing) * 100) : 0;
  return <div className="section-card"><span className="eyebrow">Official pages read</span>
    <h2>{retrieval.retrieved} of {existing} available page{existing === 1 ? "" : "s"} read <small>({coverage}% coverage)</small></h2>
    {failed.length === 0
      ? <p>Every page that exists on this site was read successfully.</p>
      : <><p>{failed.length} page{failed.length === 1 ? "" : "s"} could not be read. Confidence is reduced accordingly.</p>
          {failed.map((item, i) => <p key={i}><strong>{RETRIEVAL_LABELS[item.outcome]}</strong> — {item.url}{item.detail ? ` · ${item.detail}` : ""}</p>)}</>}
    {absent.length > 0 && <p className="hypothesis-note">{absent.length} probed page{absent.length === 1 ? " does" : "s do"} not exist on this site ({absent.map(item => new URL(item.url).pathname).join(", ")}). That is normal and does not reduce confidence.</p>}
  </div>;
}

const REJECTION_LABELS: Record<string, string> = {
  UNATTACHED_ENTITY_AMBIGUOUS: "Different or unproven entity",
  RELATED_ENTITY_ONLY: "Related company, not this one",
  REJECTED_SOURCE: "Source not suitable",
  STALE: "Too old to rely on",
};

/**
 * Blueprint section 15: show evidence that was deliberately excluded, with the
 * reason and the passage. Showing only a count asks the founder to take the
 * exclusion on faith; showing the passage lets them judge it, which is the point.
 */
function RejectedEvidencePanel({ items }: { items: Record<string, unknown>[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) {
    return <div className="section-card"><span className="eyebrow">Ambiguous or rejected evidence</span><h2>None excluded</h2><p>Every passage collected for this account passed the identity and claim-scope checks.</p></div>;
  }
  return <div className="section-card"><span className="eyebrow">Ambiguous or rejected evidence</span>
    <h2>{items.length} passage{items.length === 1 ? "" : "s"} excluded from scores and claims</h2>
    <p>These were found but deliberately not used, because they could not be tied to this company at the right scope.</p>
    <button className="secondary-button" onClick={() => setOpen(value => !value)}>{open ? "Hide details" : "Show what was excluded"}</button>
    {open && items.map((item, index) => {
      const decision = String(item.decision ?? "");
      const url = typeof item.source_url === "string" ? item.source_url : undefined;
      return <article className="claim-card" key={index}>
        <div>
          <span className="status-pill contradicted">{REJECTION_LABELS[decision] ?? decision.replaceAll("_", " ")}</span>
          <h3>{String(item.passage ?? "(no passage recorded)")}</h3>
          <p>{String(item.reason ?? "")}</p>
          <p><small>{String(item.source_domain ?? "unknown source")}{item.relation && item.relation !== "UNKNOWN" ? ` · ${String(item.relation).replaceAll("_", " ").toLowerCase()}` : ""}{item.scope ? ` · ${String(item.scope).replaceAll("_", " ").toLowerCase()}` : ""}</small></p>
        </div>
        {url && <a className="evidence-button" href={url} target="_blank" rel="noreferrer">Open source <span>↗</span></a>}
      </article>;
    })}
  </div>;
}

const REVIEW_STATES: { value: BriefState; label: string }[] = [
  { value: "RESEARCH_CANDIDATE", label: "Research candidate" },
  { value: "MONITOR", label: "Monitor" },
  { value: "IDENTITY_REVIEW_REQUIRED", label: "Identity review required" },
  { value: "DO_NOT_TARGET", label: "Do not target" },
];

/**
 * Blueprint section 17. Every action here is persisted: status changes and notes
 * become an ordered review history on the account, and corrections are recorded as
 * feedback. FOUNDER_READY is absent by design -- it is evidence-gated and the API
 * refuses to set it by hand.
 */
function ReviewPanel({ account, onReview, onFeedback, onReresearch }: { account: Brief["account"]; onReview: (status: AccountReviewStatus, state: BriefState | undefined, note: string) => Promise<void>; onFeedback: (rating: FeedbackRating, reason: string) => Promise<void>; onReresearch: () => Promise<void> }) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<BriefState | "">("");
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState("");

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    setDone("");
    try {
      await action();
      setNote("");
      setState("");
      setDone(label);
    } finally {
      setBusy("");
    }
  }

  return <div className="section-card"><span className="eyebrow">Your review</span>
    <h2>Record what you decided</h2>
    <p>Everything here is saved against the account, so whoever opens it next sees your reasoning.</p>
    <label>Note (optional)<textarea rows={3} value={note} onChange={event => setNote(event.target.value)} placeholder="Why you are making this call…" /></label>
    <label>Change state<select value={state} onChange={event => setState(event.target.value as BriefState | "")}>
      <option value="">Leave as {account.brief_state.replaceAll("_", " ")}</option>
      {REVIEW_STATES.filter(item => item.value !== account.brief_state).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select><small>FOUNDER_READY is evidence-gated and cannot be set by hand.</small></label>
    <footer className="feedback-actions">
      <button className="primary-button" disabled={Boolean(busy)} onClick={() => void run("agree", () => onReview("APPROVED", state || undefined, note))}>{busy === "agree" ? "Saving…" : "Agree and approve"}</button>
      <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("changes", () => onReview("CHANGES_REQUESTED", state || undefined, note))}>{busy === "changes" ? "Saving…" : "Request changes"}</button>
      <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("identity", () => onFeedback("WRONG_IDENTITY", note || "Flagged by reviewer as the wrong company"))}>Flag wrong identity</button>
      <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("irrelevant", () => onFeedback("BAD_ACCOUNT", note || "Flagged by reviewer as irrelevant"))}>Mark irrelevant</button>
      <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("rerun", onReresearch)}>{busy === "rerun" ? "Queueing…" : "Request re-research"}</button>
    </footer>
    {done && <p className="hypothesis-note">Saved.</p>}
    {account.review_history?.length > 0 && <><label>Review history</label>{[...account.review_history].reverse().map((entry, index) => <p key={index}><strong>{entry.review_status.replaceAll("_", " ")}</strong>{entry.brief_state ? ` · ${entry.brief_state.replaceAll("_", " ")}` : ""} · {new Date(entry.recorded_at).toLocaleString()}{entry.note ? <><br />{entry.note}</> : null}</p>)}</>}
  </div>;
}

function BriefView({ brief, openEvidence, campaignBusy, campaignAction }: { brief: Brief; openEvidence: (item: Evidence) => void; campaignBusy: boolean; campaignAction: (action: "approve" | "reject" | "edit", subject?: string, body?: string) => void }) {
  const account = brief.account;
  const [subject, setSubject] = useState(brief.campaign.subject);
  const [body, setBody] = useState(brief.campaign.body);
  const [reviewed, setReviewed] = useState(account);
  const reviewStatus = reviewed.review_status;
  const officialDomains = Array.isArray(brief.verified_identity.verified_official_domains) ? brief.verified_identity.verified_official_domains.map(String) : [];
  async function review(status: AccountReviewStatus, state: BriefState | undefined, note: string) {
    setReviewed(await api.reviewAccount(account.id, status, state, note || undefined));
  }
  async function feedback(rating: FeedbackRating, reason: string) {
    await api.feedback({ target_type: "account", target_id: account.id, rating, reason });
  }
  return <><div className="breadcrumb"><Link href="/accounts">Accounts</Link><span>/</span><span>{account.name}</span></div><section className="account-hero"><div className="account-identity"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><h2>{account.name}</h2><p>{account.domain} · {account.industry} · {account.location} · {account.employee_band} employees</p><div className="qualification-row"><span className={`qualification-pill ${brief.brief_state.toLowerCase()}`}>{brief.brief_state.replaceAll("_", " ")}</span><span>{account.provenance} · {account.import_source?.replaceAll("_", " ") ?? "AUTONOMOUS"}</span><span>{account.domain_validation} DOMAIN · {Math.round(account.domain_confidence * 100)}%</span><span>{reviewStatus.replaceAll("_", " ")}</span></div></div></div><div className="account-actions"><button className="secondary-button" onClick={() => { document.getElementById("review-panel")?.scrollIntoView({ behavior: "smooth" }); }}>Review this account</button><a className="secondary-button" href={`https://${account.domain}`} target="_blank" rel="noreferrer">Visit official site ↗</a><a className="secondary-button" href={`${API_BASE}/exports/accounts.csv`}>Export approved</a></div></section><section className="score-grid"><ScoreBadge label="Fit" score={account.scores.fit.score} /><ScoreBadge label="Intent" score={account.scores.intent.score} /><ScoreBadge label="Confidence" score={account.scores.confidence.score} /><ScoreBadge label="Priority" score={account.scores.priority} /></section><section className="brief-grid"><div>
      <div className="section-card"><span className="eyebrow">1 · Executive summary</span><h2>{brief.executive_summary || "Not enough research has run to summarise this account."}</h2><p>{officialDomains.length ? `Verified official domain: ${officialDomains.join(", ")}` : "Identity verification pending"} · Canonical domain: {account.registrable_domain ?? account.domain}</p></div>
      <div className="section-card"><span className="eyebrow">2 · Why it fits</span><h2>ICP criteria</h2>{brief.verified_icp_facts.map((claim, i) => <p key={`fit-${i}`}>✓ {claim.statement}</p>)}{brief.icp_mismatches.map((item, i) => <p key={`mismatch-${i}`}>✗ {item}</p>)}{brief.unknown_icp_facts.map((item, i) => <p key={`unknown-${i}`}>? {item}</p>)}{!brief.verified_icp_facts.length && !brief.icp_mismatches.length && !brief.unknown_icp_facts.length && <p>No ICP criteria have been evaluated yet.</p>}{brief.reason_not_to_target && <p><strong>Reason not to target:</strong> {brief.reason_not_to_target}</p>}</div>
      <div className="section-card"><span className="eyebrow">3 · Why now</span><h2>{brief.why_now.length ? "Current supported events" : "NO CURRENT HIGH-CONFIDENCE SIGNAL"}</h2>{brief.why_now.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.why_now.length && <p>No verified current event was found. That is an honest result, not a gap — monitoring remains the correct action.</p>}</div>
      <div className="section-card"><div className="section-heading"><div><span className="eyebrow">4 · Verified facts</span><h2>Supported by official sources</h2></div></div>{brief.verified_facts.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.verified_facts.length && <p>No verified company facts yet.</p>}</div>
      <div className="section-card"><span className="eyebrow">5 · Unknowns</span><h2>{brief.unknowns.length} unresolved</h2>{brief.unknowns.map((item, i) => <p key={i}>• {item}</p>)}{!brief.unknowns.length && <p>Nothing material is outstanding.</p>}</div>
      <div className="section-card"><span className="eyebrow">6 · Signals</span><h2>{brief.current_signals.length} current signal{brief.current_signals.length === 1 ? "" : "s"}</h2>{brief.current_signals.map((signal, i) => <p key={i}><strong>{signal.signal_type.replaceAll("_", " ")}</strong> · {signal.event_date ? new Date(signal.event_date).toLocaleDateString() : "no event date"} · {Math.round(signal.relevance * 100)}% relevance<br />{signal.description}</p>)}{!brief.current_signals.length && <p>None. A signal requires a real, dated event tied to this company.</p>}</div>
      <RetrievalPanel retrieval={brief.retrieval} />
      <RejectedEvidencePanel items={brief.rejected_or_ambiguous_evidence} />
      <div className="section-card"><span className="eyebrow">8 · Risks</span><h2>{brief.risks.length ? "Before acting, note" : "None recorded"}</h2>{brief.risks.map((item, i) => <p key={i}>• {item}</p>)}</div>
      <div className="section-card"><span className="eyebrow">Hypotheses</span><h2>Not verified facts</h2>{brief.hypotheses.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.hypotheses.length && <p>No hypotheses recorded.</p>}</div>
      <div className="section-card"><span className="eyebrow">11 · Sources</span><h2>{brief.sources.length} source{brief.sources.length === 1 ? "" : "s"}</h2>{brief.sources.map(source => <p key={source.id}><a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}</a><br /><small>{source.url} · retrieved {new Date(source.retrieved_at).toLocaleDateString()}</small></p>)}{!brief.sources.length && <p>No sources retrieved.</p>}</div>
    </div><aside><div className="section-card recommendation"><span className="eyebrow">9 · Recommendation</span><h2>{brief.recommended_offer}</h2><p>{brief.recommended_problem}</p><div className="action-callout">→ {brief.recommended_action}</div><label>10 · Next best action</label><p>{brief.next_research_step ?? "No further research step recorded."}</p></div><div className="section-card"><span className="eyebrow">7 · Scores</span><h2>Why this score?</h2><ScoreDetails label="Fit" breakdown={account.scores.fit} /><ScoreDetails label="Intent" breakdown={account.scores.intent} /><ScoreDetails label="Confidence" breakdown={account.scores.confidence} /></div><div id="review-panel"><ReviewPanel account={reviewed} onReview={review} onFeedback={feedback} onReresearch={async () => { await api.researchAccount(account.id); }} /></div></aside></section>{brief.brief_state === "FOUNDER_READY" ? <section className="section-card campaign-editor"><div><span className="eyebrow">Human approval required</span><h2>Campaign draft</h2><p>No message is sent by this product.</p></div><div className="draft-fields"><label>Subject<input value={subject} onChange={event => setSubject(event.target.value)} /></label><label>Draft<textarea value={body} onChange={event => setBody(event.target.value)} rows={8} /></label><footer><span className={`status-pill ${brief.campaign.status === "approved" ? "supported" : brief.campaign.status === "rejected" ? "contradicted" : "partially_supported"}`}>{brief.campaign.status}</span><button disabled={campaignBusy} className="secondary-button" onClick={() => campaignAction("edit", subject, body)}>Save edits</button><button disabled={campaignBusy} className="reject-button" onClick={() => campaignAction("reject")}>Reject</button><button disabled={campaignBusy || brief.campaign.status === "approved"} className="primary-button" onClick={() => campaignAction("approve")}>{brief.campaign.status === "approved" ? "Approved ✓" : "Approve draft ✓"}</button></footer></div></section> : <section className="section-card no-outreach"><span className="eyebrow">Human approval policy</span><h2>No outreach draft generated</h2><p>This account is not FOUNDER_READY. Resolve the documented evidence gaps or keep the account in its current review state.</p></section>}</>;
}

/**
 * Blueprint section 18: only FOUNDER_READY accounts expose an outreach draft. Both
 * of these screens previously listed every account as having a draft to review,
 * including ones whose approve button returns 409 because they are not
 * evidence-gated. Listing work that cannot be done is worse than an empty screen.
 */
function draftReadyAccounts(data: Bootstrap) {
  return data.accounts.filter(account => account.brief_state === "FOUNDER_READY");
}

function CampaignsView({ data }: { data: Bootstrap }) {
  const ready = draftReadyAccounts(data);
  return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Human-reviewed only</span><h2>Campaign drafts</h2></div></div>
    {ready.length === 0
      ? <p>No account has met the evidence gate for an outreach draft. Drafts appear only once an account reaches FOUNDER_READY, which requires verified identity, a supported ICP fact and a current supported signal. {data.accounts.length > 0 ? `${data.accounts.length} researched account${data.accounts.length === 1 ? " is" : "s are"} not there yet.` : ""}</p>
      : ready.map(account => <Link className="campaign-row" href={`/accounts/${account.id}`} key={account.id}><span className="category-icon">✦</span><div><strong>{account.name}</strong><p>{account.recommended_action}</p></div><span className="status-pill partially_supported">draft</span><b>Review →</b></Link>)}
  </section>;
}

function ApprovalsView({ data }: { data: Bootstrap }) {
  const ready = draftReadyAccounts(data);
  return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Consequential action gate</span><h2>{data.approval_count} draft{data.approval_count === 1 ? "" : "s"} need review</h2></div></div>
    {ready.length === 0
      ? <p>Nothing is waiting on you. A draft reaches this queue only when its account is evidence-gated FOUNDER_READY, and no message is ever sent without your explicit approval.</p>
      : ready.map(account => <Link className="approval-row" href={`/accounts/${account.id}`} key={account.id}><div className="company-cell"><span>{account.name.slice(0,2).toUpperCase()}</span><div><strong>{account.name}</strong><small>Campaign draft · {account.scores.priority} priority</small></div></div><p>{account.top_signal}</p><button>Review evidence and draft →</button></Link>)}
  </section>;
}
function SettingsView({ data }: { data: Bootstrap }) { const capabilities = data.capabilities ?? []; return <section className="settings-grid"><div className="section-card"><span className="eyebrow">Workspace</span><h2>{data.workspace.name}</h2><dl className="definition-list"><div><dt>Role</dt><dd>Owner</dd></div><div><dt>Data mode</dt><dd><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span></dd></div><div><dt>Research mode</dt><dd>{data.mode}</dd></div></dl></div><div className="section-card"><span className="eyebrow">Research capabilities</span><h2>{data.mode === "live" ? "Gateway health" : "Fixture provider active"}</h2><p>The system never substitutes fixtures for failed live research.</p><div className="capability-list">{(capabilities.length ? capabilities : ["Public web", "RSS", "Public GitHub", "YouTube metadata/transcripts"].map(channel => ({ channel, status: "available" as const, detail: "Gateway contract ready" }))).map(item => <div key={item.channel}><span className="status-dot" /><strong>{item.channel}</strong><small>{item.status} · {item.detail}</small></div>)}</div></div><div className="section-card"><span className="eyebrow">Data retention</span><h2>{data.retention ? `${data.retention.research_retention_days} days` : "Not configured"}</h2><p>{data.retention?.summary ?? "Retention policy is unavailable."}</p><ul className="check-list"><li>Accounts, briefs and review notes: kept until you delete them</li><li>Retrieved pages and derived evidence: {data.retention?.research_retention_days ?? "—"} days, then eligible for deletion</li><li>Automatic deletion: {data.retention?.automatic_deletion ? "enabled" : "off — an operator must review and confirm"}</li></ul></div><div className="section-card"><span className="eyebrow">Safety invariants</span><h2>Policy enforced</h2><ul className="check-list"><li>Tenant membership checked server-side</li><li>No LLM numerical scoring</li><li>No cookie-backed social scraping</li><li>No autonomous outreach</li><li>CSV formula injection protected</li></ul></div></section>; }
function Onboarding({ data }: { data: Bootstrap }) { const product = data.product; if (!product) return null; return <section className="onboarding-card"><span className="demo-badge">{data.demo_data ? "LOCAL DEMO AUTH" : "LIVE WORKSPACE"}</span><h1>Your end-to-end workspace is ready.</h1><p>{data.demo_data ? "The deterministic acceptance dataset is clearly labelled and never substitutes for live research." : "The profile is confirmed and ready for bounded public-source research."}</p><div className="onboarding-summary"><div><span>Company</span><strong>{product.company_name}</strong></div><div><span>Product</span><strong>{product.product}</strong></div><div><span>Target</span><strong>{product.target_market}</strong></div></div><Link className="primary-button large" href="/dashboard">Enter workspace →</Link></section>; }
