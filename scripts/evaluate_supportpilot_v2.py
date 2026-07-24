from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen


def percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute objective SupportPilot V2 quality metrics."
    )
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="Issue bounded HEAD requests for evidence source URLs.",
    )
    args = parser.parse_args()
    payload = json.loads(args.result.read_text(encoding="utf-8-sig"))
    if payload.get("status") == "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE":
        report = {
            "classification": "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE",
            "live_metrics_available": False,
            "provider_preflight": payload.get("providers", {}),
        }
    else:
        accounts = list(payload.get("accounts") or [])
        top = accounts[:10]
        domains = [str(item.get("domain") or "").lower() for item in accounts]
        unique_domains = set(domains)
        qualifications = Counter(
            str(item.get("qualification_status") or "UNKNOWN") for item in accounts
        )
        source_urls = {
            str(source.get("url"))
            for brief in payload.get("top_briefs") or []
            for source in brief.get("sources") or []
            if source.get("url")
        }
        link_results: dict[str, bool] = {}
        if args.check_links:
            for url in sorted(source_urls):
                try:
                    request = Request(url, method="HEAD", headers={"User-Agent": "GoPilot-QA/1.0"})
                    with urlopen(request, timeout=10) as response:
                        link_results[url] = response.status < 400
                except Exception:
                    link_results[url] = False
        report = {
            "classification": "MANUAL_QA_REQUIRED",
            "live_metrics_available": True,
            "funnel": {
                "accounts": len(accounts),
                "qualified": qualifications["QUALIFIED"],
                "qualified_with_uncertainty": qualifications[
                    "QUALIFIED_WITH_UNCERTAINTY"
                ],
                "rejected": qualifications["DISQUALIFIED"],
                "top_10": len(top),
            },
            "duplicate_rate": percentage(len(domains) - len(unique_domains), len(domains)),
            "known_size_rate": percentage(
                sum(
                    item.get("company_size_status") != "UNKNOWN"
                    for item in accounts
                ),
                len(accounts),
            ),
            "zero_signal_accounts": sum(
                not item.get("top_signal_type") for item in accounts
            ),
            "evidence_link_rate": (
                percentage(sum(link_results.values()), len(link_results))
                if link_results
                else None
            ),
            "link_checks": link_results,
            "manual_fields_required": [
                "real_company",
                "canonical_domain_correct",
                "useful_icp",
                "important_claim_supported",
                "false_entity_signal",
                "signal_relevant",
                "brief_usefulness_0_to_3",
            ],
        }
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["classification"] != "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
