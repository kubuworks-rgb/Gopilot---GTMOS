export type ClaimStatus = "supported" | "partially_supported" | "hypothesis" | "contradicted";

export interface ScoreComponent { label: string; value: number; weight: number; contribution: number; evidence_ids: string[] }
export interface ScoreBreakdown { score: number; components: ScoreComponent[] }
export interface Scores { fit: ScoreBreakdown; intent: ScoreBreakdown; confidence: ScoreBreakdown; priority: number }
export type QualificationStatus = "QUALIFIED" | "BORDERLINE" | "DISQUALIFIED" | "INSUFFICIENT_EVIDENCE";
export type CompanySizeStatus = "VERIFIED" | "ESTIMATED" | "UNKNOWN";
export type ProvenanceStatus = "USER_CONFIRMED" | "SOURCE_SUPPORTED" | "INFERRED" | "UNKNOWN";
export interface ProfileClaim { field: string; value: string | null; status: ProvenanceStatus; evidence_ids: string[]; rationale?: string }
export interface Account { id: string; name: string; domain: string; industry: string; location: string; employee_band: string; scores: Scores; top_signal: string; recommended_action: string; last_researched_at: string; qualification_status: QualificationStatus; qualification_reasons: string[]; company_size_status: CompanySizeStatus; discovery_source?: string; domain_validation: string; evidence_ids: string[]; source_ids: string[]; top_signal_type?: string }
export interface Finding { id: string; category: string; claim: string; confidence: number; status: ClaimStatus; evidence_ids: string[] }
export interface ICP { id: string; name: string; description: string; firmographics: string[]; pains: string[]; triggers: string[]; rationale: string; evidence_ids: string[]; selected: boolean; recommended: boolean; qualification_logic: string[] }
export interface Product { id: string; company_name: string; website: string; product: string; target_market: string; status: string; understanding: ProfileClaim[] }
export interface ResearchRun { id: string; status: string; current_stage: string; searches_used: number; documents_used: number; findings: Finding[] }
export interface Workspace { id: string; name: string }
export interface Capability { channel: string; status: "available" | "degraded" | "unavailable"; backend?: string; version?: string; detail?: string }
export interface Bootstrap { mode: string; demo_data: boolean; workspace: Workspace; product: Product | null; research_run: ResearchRun | null; icps: ICP[]; accounts: Account[]; approval_count: number; capabilities?: Capability[] }
export interface Evidence { id: string; source_id: string; passage: string; claim: string; confidence: number; status: ClaimStatus; observed_at: string }
export interface Source { id: string; url: string; title: string; source_type: string; platform: string; retrieved_at: string; published_at?: string; trust_score: number; demo_data: boolean }
export interface EvidenceClaim { statement: string; status: ClaimStatus; confidence: number; evidence_ids: string[] }
export interface Signal { id: string; signal_type: string; description: string; observed_at: string; strength: number; evidence_ids: string[] }
export interface Campaign { id: string; subject: string; body: string; status: "draft" | "approved" | "rejected"; evidence_ids: string[] }
export interface Brief { account: Account; why_it_fits: EvidenceClaim[]; why_now: EvidenceClaim[]; pain_hypotheses: EvidenceClaim[]; recommended_problem: string; recommended_offer: string; recommended_action: string; risks: string[]; evidence: Evidence[]; sources: Source[]; signals: Signal[]; campaign: Campaign; generated_at: string }
export type FeedbackRating = "GOOD_ACCOUNT" | "BAD_ACCOUNT" | "USEFUL_SIGNAL" | "IRRELEVANT_SIGNAL" | "CORRECT" | "INCORRECT" | "USEFUL" | "NOT_USEFUL" | "NEEDS_REVIEW";
export interface Feedback { id: string; target_type: "account" | "signal" | "finding" | "brief"; target_id: string; rating: FeedbackRating; reason?: string; notes?: string; created_at: string }
