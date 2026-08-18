"""Score any pipeline's attachment decisions against the confusable-pairs dataset.

Two ways to use it.

**Score decisions you produced elsewhere.** Emit one JSON object mapping case id
to decision, and pipe it in. Your pipeline can be written in anything.

    python run_benchmark.py --predictions my_pipeline_output.json

**See the reference implementation's score**, as a baseline to compare against:

    python run_benchmark.py --reference

The three decisions are `ATTACHED`, `RELATED_ENTITY_ONLY` and
`UNATTACHED_ENTITY_AMBIGUOUS`. A pipeline that only has attach/reject should map
both rejection kinds to `UNATTACHED_ENTITY_AMBIGUOUS` and pass
`--collapse-rejections`, which scores the two as equivalent. That is a weaker
result and the report says so, because losing the distinction between "this is
about a different company" and "we don't know" is a real loss of information.

Exit code is 0 when there are no contaminations, 1 otherwise. Contamination --
attaching evidence the dataset says must not attach -- is weighted separately
from ordinary accuracy because it is the failure that silently corrupts a
corpus, while an over-cautious rejection merely costs recall.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "confusable_pairs.v0.1.0.json"

ATTACHED = "ATTACHED"
RELATED_ONLY = "RELATED_ENTITY_ONLY"
UNATTACHED = "UNATTACHED_ENTITY_AMBIGUOUS"
REJECTIONS = {RELATED_ONLY, UNATTACHED}


def load_dataset(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def reference_predictions(dataset: dict) -> dict[str, str]:
    """Run the bundled implementation over the dataset."""
    try:
        from entity_safety import (
            ClaimScope,
            CompanyIdentityRecord,
            EntityRelation,
            VerifiedAlias,
            VerifiedEntityRelationship,
            assess_evidence_attachment,
        )
    except ModuleNotFoundError:  # pragma: no cover
        sys.exit(
            "entity_safety is not importable. Install it first:\n"
            "  pip install -e packages/entity-safety"
        )

    predictions: dict[str, str] = {}
    for case in dataset["cases"]:
        target = case["target_entity"]
        identity = CompanyIdentityRecord(
            canonical_company_name=target["name"],
            canonical_registrable_domain=target["domain"],
            verified_official_domains=tuple(target["verified_official_domains"]),
            known_aliases=tuple(
                VerifiedAlias(
                    name=alias["name"],
                    evidence_ids=("evidence-1",) if alias["evidence_backed"] else (),
                )
                for alias in target["known_aliases"]
            ),
            relationships=tuple(
                VerifiedEntityRelationship(
                    subject_domain=rel["subject_domain"],
                    object_domain=target["domain"],
                    relation=EntityRelation(rel["relation"]),
                    evidence_ids=("evidence-1",) if rel["evidence_backed"] else (),
                )
                for rel in target["known_relationships"]
            ),
            identity_confidence=0.99,
        )
        source = case["candidate_source"]
        assessment = assess_evidence_attachment(
            identity,
            source_url=source["url"],
            source_role=source["role"],
            source_title="",
            passage="",
            claim_scope=ClaimScope(source["claim_scope"]),
        )
        predictions[case["id"]] = str(assessment.decision)
    return predictions


def score(dataset: dict, predictions: dict[str, str], collapse: bool) -> dict:
    def normalise(decision: str) -> str:
        if collapse and decision in REJECTIONS:
            return "REJECTED"
        return decision

    correct = 0
    contaminations: list[dict] = []
    over_cautious: list[dict] = []
    missing: list[str] = []
    wrong_kind: list[dict] = []

    for case in dataset["cases"]:
        case_id = case["id"]
        expected = case["expected_decision"]
        if case_id not in predictions:
            missing.append(case_id)
            continue
        actual = predictions[case_id]
        if normalise(actual) == normalise(expected):
            correct += 1
            continue
        record = {
            "id": case_id,
            "label": case["label"],
            "expected": expected,
            "actual": actual,
            "why": case["why"],
        }
        if expected in REJECTIONS and actual == ATTACHED:
            # The dangerous direction: evidence about another entity accepted.
            contaminations.append(record)
        elif expected == ATTACHED and actual in REJECTIONS:
            over_cautious.append(record)
        else:
            # Both are rejections, but the wrong kind -- "different company"
            # reported as "unknown", or the reverse.
            wrong_kind.append(record)

    scored = len(dataset["cases"]) - len(missing)
    return {
        "dataset": f"{dataset['name']} v{dataset['version']}",
        "cases": len(dataset["cases"]),
        "scored": scored,
        "missing": missing,
        "correct": correct,
        "accuracy": round(correct / scored, 3) if scored else 0.0,
        "contaminations": contaminations,
        "over_cautious": over_cautious,
        "wrong_rejection_kind": wrong_kind,
        "collapsed_rejections": collapse,
    }


def report(result: dict) -> None:
    print(f"\n  {result['dataset']}")
    print(f"  {result['scored']} of {result['cases']} cases scored\n")
    if result["missing"]:
        print(f"  MISSING predictions for {len(result['missing'])} case(s):")
        for case_id in result["missing"]:
            print(f"    - {case_id}")
        print()

    print(f"  correct           {result['correct']}/{result['scored']}"
          f"  ({result['accuracy']:.1%})")
    print(f"  contaminations    {len(result['contaminations'])}"
          "   <- evidence attached that must not have been")
    print(f"  over-cautious     {len(result['over_cautious'])}"
          "   <- refused something it should have attached")
    if not result["collapsed_rejections"]:
        print(f"  wrong reject kind {len(result['wrong_rejection_kind'])}"
              "   <- rejected, but misreported why")
    else:
        print("  (rejection kinds collapsed; the related-vs-unknown distinction"
              " was not scored)")

    for title, key in (
        ("CONTAMINATIONS", "contaminations"),
        ("OVER-CAUTIOUS", "over_cautious"),
        ("WRONG REJECTION KIND", "wrong_rejection_kind"),
    ):
        if not result[key]:
            continue
        print(f"\n  {title}")
        for item in result[key]:
            print(f"    {item['label']}")
            print(f"      expected {item['expected']}, got {item['actual']}")
            print(f"      {item['why']}")

    verdict = "NO CONTAMINATION" if not result["contaminations"] else "CONTAMINATED"
    print(f"\n  {verdict}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=pathlib.Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--predictions",
        type=pathlib.Path,
        help='JSON: {"case-id": "DECISION", ...}. Use "-" for stdin.',
    )
    parser.add_argument(
        "--reference",
        action="store_true",
        help="score the bundled entity_safety implementation",
    )
    parser.add_argument(
        "--collapse-rejections",
        action="store_true",
        help="treat the two rejection kinds as equivalent",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)

    if args.reference:
        predictions = reference_predictions(dataset)
    elif args.predictions:
        raw = (
            sys.stdin.read()
            if str(args.predictions) == "-"
            else args.predictions.read_text(encoding="utf-8")
        )
        predictions = json.loads(raw)
    else:
        parser.error("pass --reference or --predictions")

    result = score(dataset, predictions, args.collapse_rejections)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        report(result)
    return 1 if result["contaminations"] or result["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
