import type { ScoreBreakdown } from "@/lib/types";

/**
 * `determined` defaults true so callers scoring something that was never
 * carried through a ScoreBreakdown (nothing in this codebase, but the default
 * keeps this component usable standalone) render exactly as before.
 */
export function ScoreBadge({ label, score, determined = true }: { label: string; score: number; determined?: boolean }) {
  if (!determined) {
    return <div className="score score-unknown" aria-label={`${label}: not determined, no evidence was available`}><span>{label}</span><strong>—</strong><small>Not determined</small></div>;
  }
  const tier = score >= 80 ? "high" : score >= 60 ? "mid" : "low";
  return <div className={`score score-${tier}`} aria-label={`${label}: ${score} out of 100`}><span>{label}</span><strong>{score}</strong><small>{tier === "high" ? "Strong" : tier === "mid" ? "Moderate" : "Low"}</small></div>;
}

export function ScoreDetails({ label, breakdown }: { label: string; breakdown: ScoreBreakdown }) {
  if (!breakdown.determined) {
    return <details className="score-details"><summary><span>{label}</span><strong>Not determined</strong></summary><p className="hypothesis-note">No evidence was available for any factor in this dimension, so it was excluded from the score rather than counted as zero.</p></details>;
  }
  return <details className="score-details"><summary><span>{label}</span><strong>{breakdown.score}</strong></summary>{breakdown.components.map(component => <div className="component-row" key={component.label}><span>{component.label}<small>{Math.round(component.weight * 100)}% weight</small></span><b>+{component.contribution.toFixed(1)}</b></div>)}</details>;
}
