export type ClaimStatus = "supported" | "partially_supported" | "hypothesis" | "contradicted";

export interface ScoreComponent { label: string; value: number; weight: number; contribution: number; evidence_ids: string[] }
export interface ScoreBreakdown { score: number; components: ScoreComponent[]; determined: boolean }
export interface Scores { fit: ScoreBreakdown; intent: ScoreBreakdown; confidence: ScoreBreakdown; priority: number }
export type QualificationStatus = "QUALIFIED" | "QUALIFIED_WITH_UNCERTAINTY" | "BORDERLINE" | "DISQUALIFIED" | "INSUFFICIENT_EVIDENCE";
export type CompanySizeStatus = "VERIFIED" | "ESTIMATED" | "UNKNOWN";
export type ProvenanceStatus = "USER_CONFIRMED" | "SOURCE_SUPPORTED" | "INFERRED" | "UNKNOWN";
export type ProductMode = "BYOA_CORE" | "AUTONOMOUS_DISCOVERY_EXPERIMENTAL";
export type BriefState = "FOUNDER_READY" | "RESEARCH_CANDIDATE" | "MONITOR" | "IDENTITY_REVIEW_REQUIRED" | "DO_NOT_TARGET";
export type AccountReviewStatus = "PENDING" | "APPROVED" | "CHANGES_REQUESTED";
export type AccountImportSource = "SINGLE" | "PASTED_DOMAINS" | "CSV_UPLOAD" | "API";
export interface ProfileClaim { field: string; value: string | null; status: ProvenanceStatus; evidence_ids: string[]; rationale?: string }
export interface Account { id: string; name: string; domain: string; industry: string; location: string; employee_band: string; scores: Scores; top_signal: string; recommended_action: string; last_researched_at: string; qualification_status: QualificationStatus; qualification_reasons: string[]; company_size_status: CompanySizeStatus; discovery_source?: string; domain_validation: string; evidence_ids: string[]; source_ids: string[]; top_signal_type?: string; registrable_domain?: string; official_subdomains: string[]; domain_confidence: number; qualification_coverage: number; priority_band: "HIGH" | "MEDIUM" | "LOW" | "MONITOR"; research_candidate: boolean; brief_state: BriefState; company_identity: Record<string, unknown>; product_mode: ProductMode; import_source?: AccountImportSource; provenance: "IMPORTED" | "DISCOVERED"; review_status: AccountReviewStatus; owner?: string | null; tags: string[]; review_history: AccountReviewEntry[] }
export interface Finding { id: string; category: string; claim: string; confidence: number; status: ClaimStatus; evidence_ids: string[] }
export interface ICP { id: string; name: string; description: string; firmographics: string[]; pains: string[]; triggers: string[]; rationale: string; evidence_ids: string[]; selected: boolean; recommended: boolean; qualification_logic: string[]; criteria_version: string; criteria: Record<string, string>[] }
export interface Product { id: string; company_name: string; website: string; product: string; target_market: string; status: string; understanding: ProfileClaim[] }
export interface ResearchRun { id: string; status: string; current_stage: string; searches_used: number; documents_used: number; max_searches?: number | null; max_documents?: number | null; findings: Finding[]; product_mode: ProductMode }
export interface Workspace { id: string; name: string }
export interface Capability { channel: string; status: "available" | "degraded" | "unavailable"; backend?: string; version?: string; detail?: string }
export interface ModeAvailability { default_mode: "BYOA_CORE"; byoa_core: "AVAILABLE"; autonomous_discovery_experimental: "AVAILABLE" | "CONFIGURATION_REQUIRED"; search_provider_configured: boolean; primary_provider: "EXA" | "TAVILY" | "NONE"; message: string }
export interface RetentionPolicy { research_retention_days: number; automatic_deletion: boolean; summary: string }
export interface Bootstrap { retention?: RetentionPolicy; mode: string; demo_data: boolean; product_mode: ProductMode; mode_availability: ModeAvailability; provider_message: string; workspace: Workspace; product: Product | null; research_run: ResearchRun | null; icps: ICP[]; accounts: Account[]; approval_count: number; capabilities?: Capability[] }
export type RetrievalOutcome = "RETRIEVED" | "TRUNCATED" | "NOT_FOUND" | "FORBIDDEN" | "UNAVAILABLE" | "TIMED_OUT" | "RATE_LIMITED" | "BLOCKED_BY_POLICY" | "UNSUPPORTED_CONTENT" | "CROSS_DOMAIN_REDIRECT";
export interface RetrievalAttempt { url: string; outcome: RetrievalOutcome; detail?: string | null }
export interface RetrievalSummary { attempted: number; retrieved: number; attempts: RetrievalAttempt[] }
export interface Evidence { id: string; source_id: string; passage: string; claim: string; confidence: number; status: ClaimStatus; observed_at: string }
export interface Source { id: string; url: string; title: string; source_type: string; platform: string; retrieved_at: string; published_at?: string; trust_score: number; demo_data: boolean }
export interface EvidenceClaim { statement: string; status: ClaimStatus; confidence: number; evidence_ids: string[] }
export interface Signal { id: string; signal_type: string; description: string; observed_at: string; strength: number; evidence_ids: string[]; entity_match_score: number; event_confidence: number; relevance: number; source_role: string; subject_entity?: string | null; canonical_subject_domain?: string | null; event_date?: string | null; source_id?: string | null; supporting_passage?: string | null; claim_scope: string; claim_scope_compatible: boolean; attachment_decision: string; rejection_reason?: string | null }
export interface Campaign { id: string; subject: string; body: string; status: "draft" | "approved" | "rejected"; evidence_ids: string[] }
export interface Brief { account: Account; why_it_fits: EvidenceClaim[]; why_now: EvidenceClaim[]; pain_hypotheses: EvidenceClaim[]; recommended_problem: string; recommended_offer: string; recommended_action: string; executive_summary: string; risks: string[]; evidence: Evidence[]; sources: Source[]; signals: Signal[]; verified_facts: EvidenceClaim[]; unknowns: string[]; research_candidate: boolean; brief_state: BriefState; verified_identity: Record<string, unknown>; verified_icp_facts: EvidenceClaim[]; icp_mismatches: string[]; unknown_icp_facts: string[]; current_signals: Signal[]; rejected_or_ambiguous_evidence: Record<string, unknown>[]; hypotheses: EvidenceClaim[]; reason_not_to_target?: string; next_research_step?: string; retrieval: RetrievalSummary; campaign: Campaign; generated_at: string }
export interface AccountImportRecord { company_name: string; domain: string; industry?: string; country?: string; employee_band?: string; notes?: string; crm_id?: string; owner?: string; tags?: string[] }
export interface AccountImportIssue { row: number; field: string; code: string; message: string }
export type ImportRowVerdict = "VALID" | "DUPLICATE" | "INVALID" | "NEEDS_REVIEW";
export interface AccountImportRow { row: number; company_name?: string | null; submitted_domain?: string | null; canonical_domain?: string | null; verdict: ImportRowVerdict; code?: string | null; reason?: string | null }
export interface AccountImportSummary { total: number; valid: number; duplicate: number; invalid: number; needs_review: number }
export interface AccountImportValidation { import_source: AccountImportSource; accepted: AccountImportRecord[]; issues: AccountImportIssue[]; duplicate_domains: string[]; rows: AccountImportRow[]; summary: AccountImportSummary }
export interface AccountImportResult { imported: { id: string; company_name: string; canonical_domain: string; import_source: AccountImportSource; provenance: "IMPORTED"; queued_for_research: boolean }[]; issues: AccountImportIssue[]; duplicate_domains: string[] }
export type FeedbackRating = "GOOD_ACCOUNT" | "BAD_ACCOUNT" | "USEFUL_SIGNAL" | "IRRELEVANT_SIGNAL" | "CORRECT" | "INCORRECT" | "USEFUL" | "NOT_USEFUL" | "NEEDS_REVIEW" | "WRONG_IDENTITY";
export interface AccountReviewEntry { actor_id: string; review_status: AccountReviewStatus; brief_state?: string | null; note?: string | null; recorded_at: string }
export interface Feedback { id: string; target_type: "account" | "signal" | "finding" | "brief"; target_id: string; rating: FeedbackRating; reason?: string; notes?: string; created_at: string }
