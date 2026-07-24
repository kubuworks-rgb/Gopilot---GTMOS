"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import type { Bootstrap, Brief, Evidence, EvidenceClaim } from "@/lib/types";
import { EvidenceDrawer } from "./evidence-drawer";
import { ScoreBadge, ScoreDetails } from "./score";

const nav = [
  ["dashboard", "Command center", "⌘"], ["product", "Product profile", "◈"],
  ["research", "Research", "⌕"], ["icps", "ICP studio", "◎"],
  ["accounts", "Accounts", "▤"], ["campaigns", "Campaigns", "✦"],
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
  const view = segments[0] ?? "home";
  const accountId = view === "accounts" ? segments[1] : undefined;
  const researchStatus = data?.research_run?.status;

  useEffect(() => { api.bootstrap().then(setData).catch(err => setError(err instanceof Error ? err.message : "Unknown API error")); }, [refresh]);
  useEffect(() => { if (accountId) api.brief(accountId).then(setBrief).catch(err => setError(err instanceof Error ? err.message : "Could not load account")); }, [accountId]);
  useEffect(() => {
    if (!researchStatus || !["queued", "planning", "researching", "extracting", "discovering_accounts", "scoring"].includes(researchStatus)) return;
    const timer = window.setInterval(() => setRefresh(value => value + 1), 3000);
    return () => window.clearInterval(timer);
  }, [researchStatus]);

  const averagePriority = useMemo(() => data?.accounts.length ? Math.round(data.accounts.reduce((sum, item) => sum + item.scores.priority, 0) / data.accounts.length) : 0, [data]);
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
      await api.startResearch(data.product.id);
      setData(await api.bootstrap());
    } finally {
      setActionBusy("");
    }
  }

  async function refreshAccounts() {
    setActionBusy("accounts");
    try {
      await api.refreshAccounts();
      setData(await api.bootstrap());
    } finally {
      setActionBusy("");
    }
  }

  const title = view === "accounts" && accountId ? brief?.account.name ?? "Account brief" : nav.find(item => item[0] === view)?.[1] ?? "Command center";
  return <div className="app-shell">
    <aside className="sidebar"><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><div className="workspace-switch"><span>Workspace</span><strong>{data.workspace.name}</strong><small>Founder workspace · Owner</small></div><nav aria-label="Primary">{nav.map(([slug, label, icon]) => <Link key={slug} href={`/${slug}`} className={view === slug ? "active" : ""}><span>{icon}</span>{label}{slug === "approvals" && data.approval_count > 0 && <b>{data.approval_count}</b>}</Link>)}</nav><div className="sidebar-footer"><span className="status-dot" /> {data.mode === "live" ? "Live research configured" : "Fixture research healthy"}<small>{data.mode === "live" ? "Public-source gateway" : "Local deterministic provider"}</small></div></aside>
    <main className="workspace"><header className="topbar"><div><span className="eyebrow">{view === "accounts" && accountId ? "Account opportunity brief" : "Evidence-backed GTM workspace"}</span><h1>{title}</h1></div><div className="top-actions"><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span><span className="avatar">KW</span></div></header>
      <div className="content">
        {view === "dashboard" && <Dashboard data={data} averagePriority={averagePriority} />}
        {view === "product" && <ProductView data={data} busy={actionBusy === "research"} onResearch={startResearch} />}
        {view === "research" && <ResearchView data={data} />}
        {view === "icps" && <ICPView data={data} busyId={icpBusy} onSelect={selectICP} />}
        {view === "accounts" && !accountId && <AccountsView data={data} busy={actionBusy === "accounts"} onRefresh={refreshAccounts} />}
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
  if (data.mode === "live") return <main className="marketing"><nav><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><Link className="primary-button" href="/dashboard">Open live workspace</Link></nav><section className="hero"><span className="demo-badge">LIVE PUBLIC DATA</span><h1>Research accounts with inspectable evidence.</h1><p>Run bounded public-source research, review deterministic scores, and keep every consequential action human-approved.</p><div className="hero-actions"><Link className="primary-button large" href="/product">Start a research run →</Link><Link className="secondary-button large" href="/settings">View capability health</Link></div></section></main>;
  return <main className="marketing"><nav><Link className="brand" href="/"><span className="brand-mark">G</span><span>GOPILOT<strong>GTM OS</strong></span></Link><div><a href="#principles">How it works</a><Link className="primary-button" href="/dashboard">Open demo workspace</Link></div></nav><section className="hero"><span className="demo-badge">DETERMINISTIC PRODUCT DEMO</span><h1>Know exactly <em>who</em> to approach—and <em>why now.</em></h1><p>Turn your market into a ranked set of defensible account opportunities. Every claim opens to its source. Every score explains its math. Every action stays human-approved.</p><div className="hero-actions"><Link className="primary-button large" href="/dashboard">Explore the command center →</Link><Link className="secondary-button large" href="/accounts">View ranked accounts</Link></div><div className="proof-row"><span>✓ Evidence-linked claims</span><span>✓ Deterministic scores</span><span>✓ Human approval</span><span>✓ No autonomous outreach</span></div></section><section className="preview"><div className="preview-header"><span><i /> GoPilot Command Center</span><span className="demo-badge">DEMO DATA</span></div><div className="preview-grid"><div><small>Ranked opportunities</small><strong>{data.accounts.length}</strong><p>Fixture accounts ready for review</p></div>{data.accounts.slice(0,2).map(account => <article key={account.id}><span>{account.industry}</span><h3>{account.name}</h3><p>{account.top_signal}</p><b>{account.scores.priority}<small>Priority</small></b></article>)}</div></section><section id="principles" className="principles"><span className="eyebrow">A different unit of value</span><h2>Not another lead scraper.</h2><div><article><b>01</b><h3>Inspect the evidence</h3><p>Material claims connect to an observed passage and original source metadata.</p></article><article><b>02</b><h3>Understand the score</h3><p>Fit and intent stay separate, confidence gates priority, and the math remains deterministic.</p></article><article><b>03</b><h3>Keep humans in control</h3><p>Drafts can be edited, approved, or rejected. The MVP never auto-sends outreach.</p></article></div></section></main>;
}

function Dashboard({ data, averagePriority }: { data: Bootstrap; averagePriority: number }) {
  return <><section className="intro-row"><div><h2>Good morning. Your market is moving.</h2><p>Research is complete and {data.accounts.length} account opportunities are ready for review.</p></div><Link className="primary-button" href="/research">View research run →</Link></section><section className="metric-grid"><div><span>Active research</span><strong>1</strong><small><i className="green-dot" /> Awaiting account review</small></div><div><span>Priority accounts</span><strong>{data.accounts.length}</strong><small>All above confidence threshold</small></div><div><span>Average priority</span><strong>{averagePriority}</strong><small>Confidence-adjusted score</small></div><div><span>Needs approval</span><strong>{data.approval_count}</strong><small>Campaign drafts, never auto-sent</small></div></section><section className="section-card"><div className="section-heading"><div><span className="eyebrow">Ranked by defensibility</span><h2>Top account opportunities</h2></div><Link href="/accounts">View all accounts →</Link></div><AccountTable data={data} compact /></section><section className="dashboard-bottom"><div className="section-card workflow-card"><div className="section-heading"><div><span className="eyebrow">Workflow</span><h2>Research run</h2></div><span className="status-pill supported">completed</span></div>{["Product profile confirmed", "Market evidence collected", "3 ICP candidates generated", "ICP selected", "Accounts scored and ranked"].map((item, i) => <div className="workflow-step" key={item}><span>✓</span><div><strong>{item}</strong><small>{i === 4 ? "Ready for human review" : "Validated"}</small></div></div>)}</div><div className="section-card signal-card"><div className="section-heading"><div><span className="eyebrow">Latest signals</span><h2>Why now</h2></div></div>{data.accounts.map(account => <Link href={`/accounts/${account.id}`} key={account.id}><span>↗</span><div><strong>{account.name}</strong><p>{account.top_signal}</p></div><small>{account.scores.intent.score} intent</small></Link>)}</div></section></>;
}

function ProductView({ data, busy, onResearch }: { data: Bootstrap; busy: boolean; onResearch: () => Promise<void> }) { const p = data.product; if (!p) return null; return <section className="two-column"><div className="section-card profile-card"><span className="eyebrow">Confirmed product profile</span><h2>{p.company_name}</h2><a href={p.website}>{p.website}</a><label>Product</label><p>{p.product}</p><label>Target market</label><p>{p.target_market}</p><label>Structured understanding</label><div className="profile-claims">{p.understanding.map(claim => <div key={claim.field}><span>{claim.field.replaceAll("_", " ")}</span><strong>{claim.value ?? "Unknown"}</strong><small className={`provenance ${claim.status.toLowerCase()}`}>{claim.status.replaceAll("_", " ")}</small></div>)}</div><div className="callout"><span>◈</span><div><strong>Evidence vs inference</strong><p>Company inputs are user-confirmed. Market conclusions remain separately evidence-linked.</p></div></div></div><div className="section-card"><span className="eyebrow">Profile status</span><h2>Ready for research</h2><dl className="definition-list"><div><dt>Status</dt><dd><span className="status-pill supported">confirmed</span></dd></div><div><dt>Research mode</dt><dd>{data.mode === "live" ? "Live public sources" : "Fixture provider"}</dd></div><div><dt>Current run</dt><dd>{data.research_run?.status ?? "Not started"}</dd></div></dl><button className="primary-button" disabled={busy} onClick={() => void onResearch()}>{busy ? "Queueing…" : data.research_run ? "Run fresh research" : "Start live research"}</button></div></section>; }

function ResearchView({ data }: { data: Bootstrap }) { const run = data.research_run; if (!run) return <section className="section-card"><h2>No research run yet</h2><p>Confirm the product profile, then start a bounded research run.</p></section>; return <><section className="research-hero"><div><span className="status-pill supported">{run.status}</span><h2>Market and ICP discovery</h2><p>Run {run.id} · {data.mode === "live" ? "live public-source research" : "deterministic fixture research"}</p></div><div><strong>{run.documents_used}</strong><span>sources</span><strong>{run.searches_used}</strong><span>searches</span></div></section><section className="finding-grid">{run.findings.map(item => <article className="finding-card" key={item.id}><div><span className="category-icon">{item.category === "market" ? "↗" : item.category === "competitor" ? "◫" : item.category === "pain_point" ? "!" : "✦"}</span><span className="eyebrow">{item.category.replace("_", " ")}</span></div><h3>{item.claim}</h3><footer><span className={`status-pill ${item.status}`}>{item.status.replace("_", " ")}</span><span>{Math.round(item.confidence * 100)}% confidence</span><span>{item.evidence_ids.length} evidence</span></footer></article>)}</section><section className="section-card budget-card"><div><span className="eyebrow">Run budget</span><h2>Bounded by policy</h2><p>Optional source failure returns partial results; it cannot crash the full workflow.</p></div><div><label>Searches <b>{run.searches_used}/60</b></label><progress value={run.searches_used} max="60" /><label>Documents <b>{run.documents_used}/100</b></label><progress value={run.documents_used} max="100" /></div></section></>; }

function ICPView({ data, busyId, onSelect }: { data: Bootstrap; busyId: string; onSelect: (icpId: string) => Promise<void> }) { return <><section className="intro-row"><div><span className="eyebrow">Exactly three candidates</span><h2>Choose the market worth learning from</h2><p>Each candidate traces its rationale to research evidence.</p></div></section><section className="icp-grid">{data.icps.map((icp, index) => <article className={`icp-card ${icp.selected ? "selected" : ""}`} key={icp.id}><header><span>ICP 0{index + 1}</span><span>{icp.recommended && <b>★ Recommended</b>}{icp.selected && <b>✓ Selected</b>}</span></header><h2>{icp.name}</h2><p>{icp.description}</p><label>Firmographics</label><div className="tag-list">{icp.firmographics.map(item => <span key={item}>{item}</span>)}</div><label>Qualification logic</label><ul>{icp.qualification_logic.map(item => <li key={item}>{item}</li>)}</ul><label>Buying triggers</label><ul>{icp.triggers.map(item => <li key={item}>{item}</li>)}</ul><footer><span>{icp.evidence_ids.length} evidence record</span><button disabled={icp.selected || Boolean(busyId)} onClick={() => void onSelect(icp.id)}>{icp.selected ? "Active ICP" : busyId === icp.id ? "Selecting…" : "Select ICP"}</button></footer></article>)}</section></>; }

function AccountTable({ data, compact = false }: { data: Bootstrap; compact?: boolean }) { return <div className="table-wrap"><table><thead><tr><th>Company</th><th>Qualification</th><th>Size evidence</th><th>Fit</th><th>Intent</th><th>Confidence</th><th>Priority</th><th>Top signal</th><th /></tr></thead><tbody>{data.accounts.slice(0, compact ? 3 : undefined).map(account => <tr key={account.id}><td><div className="company-cell"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><strong>{account.name}</strong><small>{account.domain} · {account.location}</small></div></div></td><td><span className={`qualification-pill ${account.qualification_status.toLowerCase()}`}>{account.qualification_status.replaceAll("_", " ")}</span></td><td><b>{account.employee_band}</b><small className="cell-note">{account.company_size_status}</small></td><td><b>{account.scores.fit.score}</b></td><td><b>{account.scores.intent.score}</b></td><td><b>{account.scores.confidence.score}</b></td><td><span className="priority-pill">{account.scores.priority}</span></td><td><p className="signal-text">{account.top_signal_type && <strong>{account.top_signal_type.replaceAll("_", " ")} · </strong>}{account.top_signal}</p></td><td><Link className="row-link" href={`/accounts/${account.id}`}>Open →</Link></td></tr>)}</tbody></table></div>; }
function AccountsView({ data, busy, onRefresh }: { data: Bootstrap; busy: boolean; onRefresh: () => Promise<void> }) { return <><section className="filter-bar"><input aria-label="Search accounts" placeholder="⌕  Search accounts…" /><button>Industry ▾</button><button>Geography ▾</button><button>Signal ▾</button><span>{data.accounts.length} opportunities</span>{data.mode === "live" && <button className="primary-button" disabled={busy} onClick={() => void onRefresh()}>{busy ? "Queueing…" : "Refresh accounts"}</button>}</section><section className="section-card account-table-card"><AccountTable data={data} /></section></>; }

function FeedbackButtons({ targetType, targetId }: { targetType: "account" | "signal" | "finding" | "brief"; targetId: string }) {
  const [status, setStatus] = useState("");
  async function send(rating: "GOOD_ACCOUNT" | "NEEDS_REVIEW") {
    setStatus("Saving…");
    try {
      await api.feedback({ target_type: targetType, target_id: targetId, rating });
      setStatus("Feedback saved");
    } catch {
      setStatus("Could not save");
    }
  }
  return <div className="feedback-actions"><button onClick={() => void send("GOOD_ACCOUNT")}>Good account</button><button onClick={() => void send("NEEDS_REVIEW")}>Needs review</button>{status && <small>{status}</small>}</div>;
}

function BriefView({ brief, openEvidence, campaignBusy, campaignAction }: { brief: Brief; openEvidence: (item: Evidence) => void; campaignBusy: boolean; campaignAction: (action: "approve" | "reject" | "edit", subject?: string, body?: string) => void }) { const account = brief.account; const [subject, setSubject] = useState(brief.campaign.subject); const [body, setBody] = useState(brief.campaign.body); return <><div className="breadcrumb"><Link href="/accounts">Accounts</Link><span>/</span><span>{account.name}</span></div><section className="account-hero"><div className="account-identity"><span>{account.name.slice(0, 2).toUpperCase()}</span><div><h2>{account.name}</h2><p>{account.domain} · {account.industry} · {account.location} · {account.employee_band} employees</p><div className="qualification-row"><span className={`qualification-pill ${account.qualification_status.toLowerCase()}`}>{account.qualification_status.replaceAll("_", " ")}</span><span>{account.domain_validation} DOMAIN</span><span>{account.company_size_status} SIZE</span></div></div></div><div className="account-actions"><FeedbackButtons targetType="account" targetId={account.id} /><a className="secondary-button" href={`https://${account.domain}`} target="_blank" rel="noreferrer">Visit source site ↗</a><a className="primary-button" href={`${API_BASE}/exports/accounts.csv`}>Export approved</a></div></section><section className="score-grid"><ScoreBadge label="Fit" score={account.scores.fit.score} /><ScoreBadge label="Intent" score={account.scores.intent.score} /><ScoreBadge label="Confidence" score={account.scores.confidence.score} /><ScoreBadge label="Priority" score={account.scores.priority} /></section><section className="brief-grid"><div><div className="section-card"><div className="section-heading"><div><span className="eyebrow">Defensible relevance</span><h2>Why it fits</h2></div></div>{brief.why_it_fits.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}</div><div className="section-card"><div className="section-heading"><div><span className="eyebrow">Current intent</span><h2>Why now</h2></div></div>{brief.why_now.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}<div className="timeline">{brief.signals.map(signal => <div key={signal.id}><span /><time>{new Date(signal.observed_at).toLocaleDateString()}</time><strong>{signal.description}</strong><small>{Math.round(signal.strength * 100)}% strength · {signal.signal_type}</small></div>)}</div></div><div className="section-card"><div className="section-heading"><div><span className="eyebrow">Unverified until discovery</span><h2>Pain hypotheses</h2></div></div>{brief.pain_hypotheses.map((claim, i) => <EvidenceLink key={i} claim={claim} brief={brief} open={openEvidence} />)}</div></div><aside><div className="section-card recommendation"><span className="eyebrow">Recommended next action</span><h2>{brief.recommended_offer}</h2><p>{brief.recommended_problem}</p><div className="action-callout">→ {brief.recommended_action}</div></div><div className="section-card"><span className="eyebrow">Score calculation</span><h2>Why this score?</h2><ScoreDetails label="Fit" breakdown={account.scores.fit} /><ScoreDetails label="Intent" breakdown={account.scores.intent} /><ScoreDetails label="Confidence" breakdown={account.scores.confidence} /></div></aside></section><section className="section-card campaign-editor"><div><span className="eyebrow">Human approval required</span><h2>Campaign draft</h2><p>No message is sent by this product.</p></div><div className="draft-fields"><label>Subject<input value={subject} onChange={event => setSubject(event.target.value)} /></label><label>Draft<textarea value={body} onChange={event => setBody(event.target.value)} rows={8} /></label><footer><span className={`status-pill ${brief.campaign.status === "approved" ? "supported" : brief.campaign.status === "rejected" ? "contradicted" : "partially_supported"}`}>{brief.campaign.status}</span><button disabled={campaignBusy} className="secondary-button" onClick={() => campaignAction("edit", subject, body)}>Save edits</button><button disabled={campaignBusy} className="reject-button" onClick={() => campaignAction("reject")}>Reject</button><button disabled={campaignBusy || brief.campaign.status === "approved"} className="primary-button" onClick={() => campaignAction("approve")}>{brief.campaign.status === "approved" ? "Approved ✓" : "Approve draft ✓"}</button></footer></div></section></>; }

function CampaignsView({ data }: { data: Bootstrap }) { return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Human-reviewed only</span><h2>Campaign drafts</h2></div></div>{data.accounts.map(account => <Link className="campaign-row" href={`/accounts/${account.id}`} key={account.id}><span className="category-icon">✦</span><div><strong>{account.name}</strong><p>{account.recommended_action}</p></div><span className="status-pill partially_supported">draft</span><b>Review →</b></Link>)}</section>; }
function ApprovalsView({ data }: { data: Bootstrap }) { return <section className="section-card"><div className="section-heading"><div><span className="eyebrow">Consequential action gate</span><h2>{data.approval_count} drafts need review</h2></div></div>{data.accounts.map(account => <Link className="approval-row" href={`/accounts/${account.id}`} key={account.id}><div className="company-cell"><span>{account.name.slice(0,2).toUpperCase()}</span><div><strong>{account.name}</strong><small>Campaign draft · {account.scores.priority} priority</small></div></div><p>{account.top_signal}</p><button>Review evidence and draft →</button></Link>)}</section>; }
function SettingsView({ data }: { data: Bootstrap }) { const capabilities = data.capabilities ?? []; return <section className="settings-grid"><div className="section-card"><span className="eyebrow">Workspace</span><h2>{data.workspace.name}</h2><dl className="definition-list"><div><dt>Role</dt><dd>Owner</dd></div><div><dt>Data mode</dt><dd><span className="demo-badge">{data.demo_data ? "DEMO DATA" : "LIVE PUBLIC DATA"}</span></dd></div><div><dt>Research mode</dt><dd>{data.mode}</dd></div></dl></div><div className="section-card"><span className="eyebrow">Research capabilities</span><h2>{data.mode === "live" ? "Gateway health" : "Fixture provider active"}</h2><p>The system never substitutes fixtures for failed live research.</p><div className="capability-list">{(capabilities.length ? capabilities : ["Public web", "RSS", "Public GitHub", "YouTube metadata/transcripts"].map(channel => ({ channel, status: "available" as const, detail: "Gateway contract ready" }))).map(item => <div key={item.channel}><span className="status-dot" /><strong>{item.channel}</strong><small>{item.status} · {item.detail}</small></div>)}</div></div><div className="section-card"><span className="eyebrow">Safety invariants</span><h2>Policy enforced</h2><ul className="check-list"><li>Tenant membership checked server-side</li><li>No LLM numerical scoring</li><li>No cookie-backed social scraping</li><li>No autonomous outreach</li><li>CSV formula injection protected</li></ul></div></section>; }
function Onboarding({ data }: { data: Bootstrap }) { const product = data.product; if (!product) return null; return <section className="onboarding-card"><span className="demo-badge">{data.demo_data ? "LOCAL DEMO AUTH" : "LIVE WORKSPACE"}</span><h1>Your end-to-end workspace is ready.</h1><p>{data.demo_data ? "The deterministic acceptance dataset is clearly labelled and never substitutes for live research." : "The profile is confirmed and ready for bounded public-source research."}</p><div className="onboarding-summary"><div><span>Company</span><strong>{product.company_name}</strong></div><div><span>Product</span><strong>{product.product}</strong></div><div><span>Target</span><strong>{product.target_market}</strong></div></div><Link className="primary-button large" href="/dashboard">Enter workspace →</Link></section>; }
