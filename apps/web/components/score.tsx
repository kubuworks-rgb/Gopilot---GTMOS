import type { ScoreBreakdown } from "@/lib/types";

export function ScoreBadge({ label, score }: { label: string; score: number }) {
  const tier = score >= 80 ? "high" : score >= 60 ? "mid" : "low";
  return <div className={`score score-${tier}`} aria-label={`${label}: ${score} out of 100`}><span>{label}</span><strong>{score}</strong><small>{tier === "high" ? "Strong" : tier === "mid" ? "Moderate" : "Low"}</small></div>;
}

export function ScoreDetails({ label, breakdown }: { label: string; breakdown: ScoreBreakdown }) {
  return <details className="score-details"><summary><span>{label}</span><strong>{breakdown.score}</strong></summary>{breakdown.components.map(component => <div className="component-row" key={component.label}><span>{component.label}<small>{Math.round(component.weight * 100)}% weight</small></span><b>+{component.contribution.toFixed(1)}</b></div>)}</details>;
}
