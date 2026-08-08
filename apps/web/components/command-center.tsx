"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { accessToken, api, API_BASE, serverAccessToken, subscribeToAccessToken } from "@/lib/api";
import { isOidcConfigured } from "@/lib/auth";
import type { AccountImportResult, Bootstrap, Brief, Evidence, EvidenceClaim, ResearchRun } from "@/lib/types";
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

  useEffect(() => {
    if (isCallback || !signedIn) return;
    api.bootstrap().then(setData).catch(err => setError(err instanceof Error ? err.message : "Unknown API error"));
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

  async function importAccounts(kind: "single" | "pasted" | "csv", value: { company_name: string; domain: string } | string) {
    const current = data;
    if (!current?.product) return;
    setActionBusy("import");
    try {
      if (!current.research_run || current.research_run.product_mode !== "BYOA_CORE") {
        await api.startResearch(current.product.id, "BYOA_CORE");
      }
      const result = kind === "single"
        ? await api.importSingle(value as { company_name: string; domain: string })
        : kind === "pasted"
          ? await api.importPasted(value as string)
          : await api.importCsv(value as string);
      setImportResult(result);
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
    <aside className="sidebar"><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><div className="workspace-switch"><span>Workspace</span><strong>{data.workspace.name}</strong><small>Founder workspace · Owner</small></div><nav aria-label="Primary">{nav.map(([slug, label, icon]) => <Link key={slug} href={`/${slug}`} className={`${view === slug ? "active" : ""} ${slug === "discovery" ? "experimental-nav" : ""}`}><span>{icon}</span>{label}{slug === "discovery" && <small>EXPERIMENTAL</small>}{slug === "approvals" && data.approval_count > 0 && <b>{data.approval_count}</b>}</Link>)}</nav><div className="sidebar-footer"><span className="status-dot" /> BYOA core available<small>{data.provider_message}</small>{isOidcConfigured() && <button className="secondary-button" onClick={() => signOut()}>Sign out</button>}</div></aside>
    <main className="workspace"><header className="topbar"><div><span className="eyebrow">{view === "accounts" && accountId ? "Account opportunity brief" : "Evidence-backed GTM workspace"}</span><h1>{title}</h1></div><div className="top-actions"><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span><span className="avatar">KW</span></div></header>
      <div className="content">
        {view === "dashboard" && <Dashboard data={data} averagePriority={averagePriority} />}
        {view === "import" && <ImportAccountsView busy={actionBusy === "import"} result={importResult} onImport={importAccounts} />}
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
    <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Ranked by defensibility</span><h2>Top account opportunities</h2></div><Link href="/accounts">View all accounts →</Link></div><AccountTable data={data} compact /></section>
    <section className="dashboard-bottom">
      <div className="section-card workflow-card"><div className="section-heading"><div><span className="eyebrow">Workflow</span><h2>Progress</h2></div><span className={`status-pill ${runActive ? "partially_supported" : run ? "supported" : ""}`}>{run ? (runActive ? "in progress" : run.status) : "not started"}</span></div>{steps.map(([label, done, detail]) => <div className="workflow-step" key={label}><span>{done ? "✓" : "○"}</span><div><strong>{label}</strong><small>{detail}</small></div></div>)}</div>
      <div className="section-card signal-card"><div className="section-heading"><div><span className="eyebrow">Verified current signals</span><h2>Why now</h2></div></div>{withSignal.length ? withSignal.map(account => <Link href={`/accounts/${account.id}`} key={account.id}><span>↗</span><div><strong>{account.name}</strong><p>{account.top_signal}</p></div><small>{account.scores.intent.score} intent</small></Link>) : <p>No account has a verified current signal. NO_SIGNAL is a valid result — monitoring remains the correct action.</p>}</div>
    </section></>;
}

function ImportAccountsView({ busy, result, onImport }: { busy: boolean; result: AccountImportResult | null; onImport: (kind: "single" | "pasted" | "csv", value: { company_name: string; domain: string } | string) => Promise<void> }) {
  const [method, setMethod] = useState<"single" | "pasted" | "csv">("single");
  const [company, setCompany] = useState("");
  const [domain, setDomain] = useState("");
  const [bulk, setBulk] = useState("");
  return <section className="import-workflow">
    <div className="workflow-strip">{["Import Accounts", "Validate Accounts", "Research Accounts", "Review Priorities", "Inspect Briefs", "Approve or Change Status", "Export"].map((item, index) => <span className={index === 0 ? "active" : ""} key={item}>{index + 1}. {item}</span>)}</div>
    <div className="section-card import-card">
      <div><span className="eyebrow">BYOA core · default mode</span><h2>Import accounts you already care about</h2><p>Account research uses supplied official domains and remains available without Exa or Tavily.</p></div>
      <div className="import-tabs">{(["single", "pasted", "csv"] as const).map(item => <button className={method === item ? "active" : ""} key={item} onClick={() => setMethod(item)}>{item === "single" ? "Single account" : item === "pasted" ? "Pasted domains" : "CSV upload"}</button>)}</div>
      {method === "single" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("single", { company_name: company, domain }); }}><label>Company name<input required minLength={2} value={company} onChange={event => setCompany(event.target.value)} placeholder="Acme Software" /></label><label>Official domain<input required value={domain} onChange={event => setDomain(event.target.value)} placeholder="acme.com" /></label><button className="primary-button" disabled={busy} type="submit">{busy ? "Validating…" : "Validate and import"}</button></form>}
      {method === "pasted" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("pasted", bulk); }}><label>One domain per line<textarea required rows={10} value={bulk} onChange={event => setBulk(event.target.value)} placeholder={"Acme, acme.com\nexample.org"} /></label><button className="primary-button" disabled={busy} type="submit">{busy ? "Validating…" : "Validate and import"}</button></form>}
      {method === "csv" && <form className="import-form" onSubmit={event => { event.preventDefault(); void onImport("csv", bulk); }}><label>CSV file<input required type="file" accept=".csv,text/csv" onChange={event => { const file = event.target.files?.[0]; if (file) void file.text().then(setBulk); }} /></label><small>Required headers: company_name, domain. Optional: industry, country, employee_band, notes, crm_id, owner, tags.</small><button className="primary-button" disabled={busy || !bulk} type="submit">{busy ? "Validating…" : "Validate and import"}</button></form>}
      {result && <div className="import-result"><strong>{result.imported.length} accounts imported</strong><span>{result.duplicate_domains.length} duplicates skipped</span>{result.issues.map((issue, index) => <small key={`${issue.code}-${index}`}>Row {issue.row}: {issue.message}</small>)}{result.imported.length > 0 && <Link className="primary-button" href="/accounts">Research imported accounts →</Link>}</div>}
    </div>
  </section>;
}

function ExperimentalDiscoveryView({ data, busy, onStart }: { data: Bootstrap; busy: boolean; onStart: () => Promise<void> }) {
  const available = data.mode_availability.autonomous_discovery_experimental === "AVAILABLE";
  return <section className="section-card experimental-card"><span className="demo-badge">EXPERIMENTAL</span><h2>Automatic account discovery</h2><p>This secondary workflow may surface useful research candidates, but every result requires human review and must not be treated as founder-ready by default.</p><div className="warning-callout"><strong>Human review required</strong><span>{data.provider_message}</span></div><dl className="definition-list"><div><dt>Status</dt><dd>{available ? "Provider configured" : "Configuration required"}</dd></div><div><dt>Core account research</dt><dd>Available</dd></div><div><dt>Production promise</dt><dd>Experimental candidates only</dd></div></dl><button className="primary-button" disabled={busy || !available} onClick={() => void onStart()}>{busy ? "Queueing…" : available ? "Start experimental discovery" : "Search provider configuration required"}</button></section>;
}

function ProductView({ data, busy, onResearch }: { data: Bootstrap; busy: boolean; onResearch: () => Promise<void> }) { const p = data.product; if (!p) return null; return <section className="two-column"><div className="section-card profile-card"><span className="eyebrow">Confirmed product profile</span><h2>{p.company_name}</h2><a href={p.website}>{p.website}</a><label>Product</label><p>{p.product}</p><label>Target market</label><p>{p.target_market}</p><label>Structured understanding</label><div className="profile-claims">{p.understanding.map(claim => <div key={claim.field}><span>{claim.field.replaceAll("_", " ")}</span><strong>{claim.value ?? "Unknown"}</strong><small className={`provenance ${claim.status.toLowerCase()}`}>{claim.status.replaceAll("_", " ")}</small></div>)}</div><div className="callout"><span>◈</span><div><strong>Evidence vs inference</strong><p>Company inputs are user-confirmed. Market conclusions remain separately evidence-linked.</p></div></div></div><div className="section-card"><span className="eyebrow">Profile status</span><h2>Ready for research</h2><dl className="definition-list"><div><dt>Status</dt><dd><span className="status-pill supported">confirmed</span></dd></div><div><dt>Research mode</dt><dd>{data.mode === "live" ? "Live public sources" : "Fixture provider"}</dd></div><div><dt>Current run</dt><dd>{data.research_run?.status ?? "Not started"}</dd></div></dl><button className="primary-button" disabled={busy} onClick={() => void onResearch()}>{busy ? "Queueing…" : data.research_run ? "Run fresh research" : "Start live research"}</button></div></section>; }

function ResearchView({ data }: { data: Bootstrap }) { const run = data.research_run; if (!run) return <section className="section-card"><h2>No research run yet</h2><p>Confirm the product profile, then start a bounded research run.</p></section>; return <><section className="research-hero"><div><span className="status-pill supported">{run.status}</span><h2>Market and ICP discovery</h2><p>Run {run.id} · {data.mode === "live" ? "live public-source research" : "deterministic fixture research"}</p></div><div><strong>{run.documents_used}</strong><span>sources</span><strong>{run.searches_used}</strong><span>searches</span></div></section><section className="finding-grid">{run.findings.map(item => <article className="finding-card" key={item.id}><div><span className="category-icon">{item.category === "market" ? "↗" : item.category === "competitor" ? "◫" : item.category === "pain_point" ? "!" : "✦"}</span><span className="eyebrow">{item.category.replace("_", " ")}</span></div><h3>{item.claim}</h3><footer><span className={`status-pill ${item.status}`}>{item.status.replace("_", " ")}</span><span>{Math.round(item.confidence * 100)}% confidence</span><span>{item.evidence_ids.length} evidence</span></footer></article>)}</section><section className="section-card budget-card"><div><span className="eyebrow">Run budget</span><h2>Bounded by policy</h2><p>Optional source failure returns partial results; it cannot crash the full workflow.</p></div><div><label>Searches <b>{run.searches_used}/60</b></label><progress value={run.searches_used} max="60" /><label>Documents <b>{run.documents_used}/100</b></label><progress value={run.documents_used} max="100" /></div></section></>; }

function ICPView({ data, busyId, onSelect }: { data: Bootstrap; busyId: string; onSelect: (icpId: string) => Promise<void> }) { return <><section className="intro-row"><div><span className="eyebrow">Exactly three candidates</span><h2>Choose the market worth learning from</h2><p>Each candidate traces its rationale to research evidence.</p></div></section><section className="icp-grid">{data.icps.map((icp, index) => <article className={`icp-card ${icp.selected ? "selected" : ""}`} key={icp.id}><header><span>ICP 0{index + 1}</span><span>{icp.recommended && <b>★ Recommended</b>}{icp.selected && <b>✓ Selected</b>}</span></header><h2>{icp.name}</h2><p>{icp.description}</p><label>Firmographics</label><div className="tag-list">{icp.firmographics.map(item => <span key={item}>{item}</span>)}</div><label>Qualification logic</label><ul>{icp.qualification_logic.map(item => <li key={item}>{item}</li>)}</ul><label>Buying triggers</label><ul>{icp.triggers.map(item => <li key={item}>{item}</li>)}</ul><footer><span>{icp.evidence_ids.length} evidence record</span><button disabled={icp.selected || Boolean(busyId)} onClick={() => void onSelect(icp.id)}>{icp.selected ? "Active ICP" : busyId === icp.id ? "Selecting…" : "Select ICP"}</button></footer></article>)}</section></>; }

function AccountTable({ data, compact = false }: { data: Bootstrap; compact?: boolean }) {
  return <div className="table-wrap"><table><thead><tr><th>Company</th><th>Provenance</th><th>Status</th><th>Fit</th><th>Intent</th><th>Confidence</th><th>Priority</th><th>Top signal</th><th /></tr></thead><tbody>{data.accounts.slice(0, compact ? 3 : undefined).map(account => <tr key={account.id}><td><div className="company-cell"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><strong>{account.name}</strong><small>{account.domain} · {account.location}</small></div></div></td><td><span className={`provenance-badge ${account.provenance.toLowerCase()}`}>{account.provenance}</span><small className="cell-note">{account.import_source?.replaceAll("_", " ") ?? "AUTONOMOUS DISCOVERY"}</small></td><td><span className={`qualification-pill ${account.qualification_status.toLowerCase()}`}>{account.brief_state.replaceAll("_", " ")}</span><small className="cell-note">{account.review_status.replaceAll("_", " ")}</small></td><td><b>{account.scores.fit.score}</b></td><td><b>{account.scores.intent.score}</b></td><td><b>{account.scores.confidence.score}</b></td><td><span className="priority-pill">{account.priority_band} · {account.scores.priority}</span></td><td><p className="signal-text">{account.top_signal_type && <strong>{account.top_signal_type.replaceAll("_", " ")} · </strong>}{account.top_signal}</p></td><td><Link className="row-link" href={`/accounts/${account.id}`}>Inspect →</Link></td></tr>)}</tbody></table></div>;
}
function AccountsView({ data }: { data: Bootstrap }) { return <><section className="filter-bar"><input aria-label="Search accounts" placeholder="⌕  Search accounts…" /><button>Industry ▾</button><button>Review status ▾</button><button>Brief state ▾</button><span>{data.accounts.length} accounts</span><Link className="primary-button" href="/import">Import accounts</Link></section><section className="section-card account-table-card"><AccountTable data={data} /></section></>; }

function BriefView({ brief, openEvidence, campaignBusy, campaignAction }: { brief: Brief; openEvidence: (item: Evidence) => void; campaignBusy: boolean; campaignAction: (action: "approve" | "reject" | "edit", subject?: string, body?: string) => void }) {
  const account = brief.account;
  const [subject, setSubject] = useState(brief.campaign.subject);
  const [body, setBody] = useState(brief.campaign.body);
  const [reviewStatus, setReviewStatus] = useState(account.review_status);
  const officialDomains = Array.isArray(brief.verified_identity.verified_official_domains) ? brief.verified_identity.verified_official_domains.map(String) : [];
  async function review(status: "APPROVED" | "CHANGES_REQUESTED") {
    const updated = await api.reviewAccount(account.id, status);
    setReviewStatus(updated.review_status);
  }
  return <><div className="breadcrumb"><Link href="/accounts">Accounts</Link><span>/</span><span>{account.name}</span></div><section className="account-hero"><div className="account-identity"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><h2>{account.name}</h2><p>{account.domain} · {account.industry} · {account.location} · {account.employee_band} employees</p><div className="qualification-row"><span className={`qualification-pill ${account.qualification_status.toLowerCase()}`}>{brief.brief_state.replaceAll("_", " ")}</span><span>{account.provenance} · {account.import_source?.replaceAll("_", " ") ?? "AUTONOMOUS"}</span><span>{account.domain_validation} DOMAIN · {Math.round(account.domain_confidence * 100)}%</span><span>{reviewStatus.replaceAll("_", " ")}</span></div></div></div><div className="account-actions"><button className="secondary-button" onClick={() => void review("CHANGES_REQUESTED")}>Change status</button><button className="primary-button" onClick={() => void review("APPROVED")}>Approve for export</button><a className="secondary-button" href={`https://${account.domain}`} target="_blank" rel="noreferrer">Visit official site ↗</a><a className="secondary-button" href={`${API_BASE}/exports/accounts.csv`}>Export approved</a></div></section><section className="score-grid"><ScoreBadge label="Fit" score={account.scores.fit.score} /><ScoreBadge label="Intent" score={account.scores.intent.score} /><ScoreBadge label="Confidence" score={account.scores.confidence.score} /><ScoreBadge label="Priority" score={account.scores.priority} /></section><section className="brief-grid"><div><div className="section-card"><span className="eyebrow">Verified company identity</span><h2>{officialDomains.length ? officialDomains.join(", ") : "Identity verification pending"}</h2><p>Canonical domain: {account.registrable_domain ?? account.domain}</p></div><div className="section-card"><div className="section-heading"><div><span className="eyebrow">Verified public evidence</span><h2>Known facts and ICP matches</h2></div></div>{brief.verified_facts.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.verified_facts.length && <p>No verified company facts yet.</p>}</div><div className="section-card"><span className="eyebrow">ICP mismatches and unknown criteria</span><h2>Evidence gaps</h2>{brief.icp_mismatches.map((item, i) => <p key={`mismatch-${i}`}><strong>Mismatch:</strong> {item}</p>)}{brief.unknown_icp_facts.map((item, i) => <p key={i}>• {item}</p>)}{brief.reason_not_to_target && <p><strong>Reason not to target:</strong> {brief.reason_not_to_target}</p>}</div><div className="section-card"><span className="eyebrow">Current supported signals</span><h2>Why now</h2>{brief.why_now.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.why_now.length && <p>NO_SIGNAL — no verified current event. Monitor remains valid.</p>}</div><div className="section-card"><span className="eyebrow">Ambiguous or rejected evidence</span><h2>Excluded from scores and claims</h2><p>{brief.rejected_or_ambiguous_evidence.length} evidence items rejected or held for review.</p></div><div className="section-card"><span className="eyebrow">Hypotheses</span><h2>Not verified facts</h2>{brief.hypotheses.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}{!brief.hypotheses.length && <p>No hypotheses recorded.</p>}</div></div><aside><div className="section-card recommendation"><span className="eyebrow">Recommended next action</span><h2>{brief.recommended_offer}</h2><p>{brief.recommended_problem}</p><div className="action-callout">→ {brief.recommended_action}</div><p>{brief.next_research_step ?? "No further research step recorded."}</p></div><div className="section-card"><span className="eyebrow">Deterministic score calculation</span><h2>Why this score?</h2><ScoreDetails label="Fit" breakdown={account.scores.fit} /><ScoreDetails label="Intent" breakdown={account.scores.intent} /><ScoreDetails label="Confidence" breakdown={account.scores.confidence} /></div></aside></section>{brief.brief_state === "FOUNDER_READY" ? <section className="section-card campaign-editor"><div><span className="eyebrow">Human approval required</span><h2>Campaign draft</h2><p>No message is sent by this product.</p></div><div className="draft-fields"><label>Subject<input value={subject} onChange={event => setSubject(event.target.value)} /></label><label>Draft<textarea value={body} onChange={event => setBody(event.target.value)} rows={8} /></label><footer><span className={`status-pill ${brief.campaign.status === "approved" ? "supported" : brief.campaign.status === "rejected" ? "contradicted" : "partially_supported"}`}>{brief.campaign.status}</span><button disabled={campaignBusy} className="secondary-button" onClick={() => campaignAction("edit", subject, body)}>Save edits</button><button disabled={campaignBusy} className="reject-button" onClick={() => campaignAction("reject")}>Reject</button><button disabled={campaignBusy || brief.campaign.status === "approved"} className="primary-button" onClick={() => campaignAction("approve")}>{brief.campaign.status === "approved" ? "Approved ✓" : "Approve draft ✓"}</button></footer></div></section> : <section className="section-card no-outreach"><span className="eyebrow">Human approval policy</span><h2>No outreach draft generated</h2><p>This account is not FOUNDER_READY. Resolve the documented evidence gaps or keep the account in its current review state.</p></section>}</>;
}

function CampaignsView({ data }: { data: Bootstrap }) { return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Human-reviewed only</span><h2>Campaign drafts</h2></div></div>{data.accounts.map(account => <Link className="campaign-row" href={`/accounts/${account.id}`} key={account.id}><span className="category-icon">✦</span><div><strong>{account.name}</strong><p>{account.recommended_action}</p></div><span className="status-pill partially_supported">draft</span><b>Review →</b></Link>)}</section>; }
function ApprovalsView({ data }: { data: Bootstrap }) { return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Consequential action gate</span><h2>{data.approval_count} drafts need review</h2></div></div>{data.accounts.map(account => <Link className="approval-row" href={`/accounts/${account.id}`} key={account.id}><div className="company-cell"><span>{account.name.slice(0,2).toUpperCase()}</span><div><strong>{account.name}</strong><small>Campaign draft · {account.scores.priority} priority</small></div></div><p>{account.top_signal}</p><button>Review evidence and draft →</button></Link>)}</section>; }
function SettingsView({ data }: { data: Bootstrap }) { const capabilities = data.capabilities ?? []; return <section className="settings-grid"><div className="section-card"><span className="eyebrow">Workspace</span><h2>{data.workspace.name}</h2><dl className="definition-list"><div><dt>Role</dt><dd>Owner</dd></div><div><dt>Data mode</dt><dd><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span></dd></div><div><dt>Research mode</dt><dd>{data.mode}</dd></div></dl></div><div className="section-card"><span className="eyebrow">Research capabilities</span><h2>{data.mode === "live" ? "Gateway health" : "Fixture provider active"}</h2><p>The system never substitutes fixtures for failed live research.</p><div className="capability-list">{(capabilities.length ? capabilities : ["Public web", "RSS", "Public GitHub", "YouTube metadata/transcripts"].map(channel => ({ channel, status: "available" as const, detail: "Gateway contract ready" }))).map(item => <div key={item.channel}><span className="status-dot" /><strong>{item.channel}</strong><small>{item.status} · {item.detail}</small></div>)}</div></div><div className="section-card"><span className="eyebrow">Safety invariants</span><h2>Policy enforced</h2><ul className="check-list"><li>Tenant membership checked server-side</li><li>No LLM numerical scoring</li><li>No cookie-backed social scraping</li><li>No autonomous outreach</li><li>CSV formula injection protected</li></ul></div></section>; }
function Onboarding({ data }: { data: Bootstrap }) { const product = data.product; if (!product) return null; return <section className="onboarding-card"><span className="demo-badge">{data.demo_data ? "LOCAL DEMO AUTH" : "LIVE WORKSPACE"}</span><h1>Your end-to-end workspace is ready.</h1><p>{data.demo_data ? "The deterministic acceptance dataset is clearly labelled and never substitutes for live research." : "The profile is confirmed and ready for bounded public-source research."}</p><div className="onboarding-summary"><div><span>Company</span><strong>{product.company_name}</strong></div><div><span>Product</span><strong>{product.product}</strong></div><div><span>Target</span><strong>{product.target_market}</strong></div></div><Link className="primary-button large" href="/dashboard">Enter workspace →</Link></section>; }
