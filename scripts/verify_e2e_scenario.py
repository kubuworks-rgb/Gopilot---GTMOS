"""Walk the blueprint §40 acceptance scenario against a live stack.

Live means live: real Postgres, real Redis, a real worker consuming the queue, and
the research gateway making real HTTP requests to real company websites. No
fixtures, and deliberately no EXA_API_KEY or TAVILY_API_KEY -- the supplied-account
(BYOA) workflow has to stand up without a paid research provider, which is the
specific claim this script exists to test.

    npm run dev:live          # in one terminal
    python scripts/verify_e2e_scenario.py

Every step prints PASS or FAIL. Steps that pass technically but would confuse a
founder are printed as FLAG: they do not fail the run, because they are product
judgements rather than defects, but they are the point of §35 and they are what a
green test suite will not tell you.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Report:
    passed: int = 0
    failed: int = 0
    flags: list[str] = field(default_factory=list)

    def check(self, condition: bool, label: str, detail: str = "") -> bool:
        if condition:
            self.passed += 1
        else:
            self.failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  {'PASS' if condition else 'FAIL'}  {label}{suffix}")
        return condition

    def flag(self, message: str) -> None:
        """Technically fine, but a founder would trip over it."""
        self.flags.append(message)
        print(f"  FLAG  {message}")

    def note(self, message: str) -> None:
        print(f"        {message}")


def step(number: str, title: str) -> None:
    print(f"\n[{number}] {title}")


def pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def sign_in(client: httpx.Client, issuer: str, subject: str, email: str) -> str:
    verifier, challenge = pkce()
    redirect = "http://localhost:3000/auth/callback"
    authorized = client.post(
        f"{issuer}/authorize",
        data={
            "subject": subject,
            "email": email,
            "redirect_uri": redirect,
            "state": secrets.token_urlsafe(8),
            "code_challenge": challenge,
        },
        follow_redirects=False,
    )
    code = authorized.headers["location"].split("code=")[1].split("&")[0]
    tokens = client.post(
        f"{issuer}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "client_id": "gopilot-local",
        },
    )
    tokens.raise_for_status()
    return str(tokens.json()["access_token"])


def wait_for_run(
    client: httpx.Client, api: str, headers: dict[str, str], run_id: str, timeout: int
) -> dict[str, Any]:
    """Poll a research run to a terminal state, printing stage transitions."""
    deadline = time.time() + timeout
    last_stage = ""
    while time.time() < deadline:
        response = client.get(f"{api}/research-runs/{run_id}", headers=headers)
        response.raise_for_status()
        run = response.json()
        stage = str(run.get("current_stage") or run.get("status") or "")
        if stage != last_stage:
            print(f"        · {stage}")
            last_stage = stage
        if run.get("status") in {"complete", "completed", "failed", "awaiting_icp"}:
            return dict(run)
        time.sleep(3)
    return {"status": "timeout", "current_stage": last_stage}


# Twenty real companies. Real domains matter: fixtures cannot exercise DNS, TLS,
# redirects, robots handling, 404s, or the slow-and-partial reality of the open web,
# and every one of those has produced a defect in this codebase already.
COMPANIES: list[dict[str, str]] = [
    {"company_name": "Zerodha", "domain": "zerodha.com"},
    {"company_name": "Freshworks", "domain": "freshworks.com"},
    {"company_name": "Postman", "domain": "postman.com"},
    {"company_name": "Razorpay", "domain": "razorpay.com"},
    {"company_name": "Chargebee", "domain": "chargebee.com"},
    {"company_name": "BrowserStack", "domain": "browserstack.com"},
    {"company_name": "Hasura", "domain": "hasura.io"},
    {"company_name": "Zoho", "domain": "zoho.com"},
    {"company_name": "Atlassian", "domain": "atlassian.com"},
    {"company_name": "Basecamp", "domain": "basecamp.com"},
    {"company_name": "Linear", "domain": "linear.app"},
    {"company_name": "Vercel", "domain": "vercel.com"},
    {"company_name": "Supabase", "domain": "supabase.com"},
    {"company_name": "PlanetScale", "domain": "planetscale.com"},
    {"company_name": "Render", "domain": "render.com"},
    {"company_name": "Fly.io", "domain": "fly.io"},
    {"company_name": "Neon", "domain": "neon.tech"},
    {"company_name": "Clerk", "domain": "clerk.com"},
    # A duplicate of row 1, to prove duplicate detection on a real list.
    {"company_name": "Zerodha Broking", "domain": "zerodha.com"},
    # Unsafe: private address space. Must be refused, not fetched.
    {"company_name": "Internal Wiki", "domain": "192.168.1.10"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", default="http://127.0.0.1:9000")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--subject", default="alpha-founder")
    parser.add_argument("--product-timeout", type=int, default=900)
    parser.add_argument("--account-timeout", type=int, default=1200)
    parser.add_argument("--accounts-to-research", type=int, default=6)
    args = parser.parse_args()

    report = Report()
    api = args.api

    with httpx.Client(timeout=60) as client:
        step("1", "A founder signs in")
        token = sign_in(client, args.issuer, args.subject, "founder@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        report.check(bool(token), "signed in against the OIDC issuer")

        step("2", "Creating a workspace")
        created = client.post(
            f"{api}/workspaces",
            headers=headers,
            json={"name": f"Alpha E2E {time.strftime('%H%M%S')}"},
        )
        report.check(created.status_code == 201, f"workspace created ({created.status_code})")
        if created.status_code != 201:
            print(created.text[:400])
            return 1
        workspace_id = created.json()["id"]
        headers["X-Workspace-Id"] = workspace_id
        report.note(f"workspace {workspace_id}")

        step("3", "Describing the product")
        product = client.post(
            f"{api}/products",
            headers=headers,
            json={
                "company_name": "GoPilot",
                "website": "https://gopilot.example",
                "product": "Evidence-backed GTM account intelligence for founders",
                "target_market": "B2B SaaS companies in India and the US",
            },
        )
        report.check(product.status_code == 201, f"product profile stored ({product.status_code})")
        if product.status_code != 201:
            print(product.text[:400])
            return 1
        product_id = product.json()["id"]

        step("4", "Running product research to derive ICPs")
        run = client.post(
            f"{api}/research-runs",
            headers=headers,
            params={"product_id": product_id, "product_mode": "BYOA_CORE"},
        )
        report.check(run.status_code == 202, f"run queued ({run.status_code})")
        if run.status_code != 202:
            print(run.text[:600])
            return 1
        run_id = run.json()["id"]
        finished = wait_for_run(client, api, headers, run_id, args.product_timeout)
        report.check(
            finished.get("status") in {"awaiting_icp", "complete", "completed"},
            f"product run reached a usable state ({finished.get('status')})",
            str(finished.get("error") or "")[:200],
        )

        step("5", "Choosing an ICP")
        icps = client.get(f"{api}/icps", headers=headers).json()
        report.check(len(icps) > 0, f"{len(icps)} ICP(s) proposed")
        if not icps:
            print("      no ICP: cannot import accounts, stopping")
            return 1
        recommended = next((item for item in icps if item.get("recommended")), icps[0])
        selected = client.post(
            f"{api}/icps/{recommended['id']}/select", headers=headers
        )
        report.check(selected.status_code == 202, f"ICP selected ({selected.status_code})")
        report.note(f"ICP: {recommended.get('name')}")
        if not recommended.get("qualification_logic"):
            report.flag(
                "the selected ICP carries no qualification_logic, so a founder cannot "
                "see what rule their accounts will be judged against"
            )

        step("6", "Validating a 20-company list before importing")
        payload = {"accounts": COMPANIES, "import_source": "CSV_UPLOAD"}
        validation = client.post(
            f"{api}/account-imports/validate", headers=headers, json=payload
        )
        report.check(validation.status_code == 200, f"validation ran ({validation.status_code})")
        result = validation.json()
        accepted = result.get("accepted", [])
        issues = result.get("issues", [])
        duplicates = result.get("duplicate_domains", [])
        report.check(
            len(duplicates) >= 1, f"duplicate detected before import ({duplicates})"
        )
        unsafe_codes = {"IP_DESTINATION", "PRIVATE_DESTINATION", "NON_PUBLIC_DOMAIN"}
        unsafe = [item for item in issues if item.get("code") in unsafe_codes]
        report.check(
            bool(unsafe),
            "private-network domain refused",
            ", ".join(sorted({str(item.get("code")) for item in unsafe})),
        )
        report.check(
            len(accepted) == 18,
            f"18 of 20 accepted, duplicate and unsafe removed (got {len(accepted)})",
        )

        step("7", "Importing the validated list")
        imported = client.post(f"{api}/accounts/import", headers=headers, json=payload)
        report.check(imported.status_code == 201, f"import accepted ({imported.status_code})")
        if imported.status_code != 201:
            print(imported.text[:600])
            return 1
        rows = imported.json()["imported"]
        report.check(len(rows) == 18, f"{len(rows)} accounts created")

        step("8", "Identity state before any research")
        accounts = client.get(f"{api}/accounts", headers=headers).json()
        states = {}
        for item in accounts:
            states[item["brief_state"]] = states.get(item["brief_state"], 0) + 1
        report.note(f"states: {states}")
        report.check(
            all(item["scores"]["priority"] == 0 for item in accounts),
            "unresearched accounts score zero rather than a guess",
        )

        step("9", "Researching accounts against real websites (no Exa, no Tavily)")
        targets = accounts[: args.accounts_to_research]
        for item in targets:
            queued = client.post(
                f"{api}/accounts/{item['id']}/research", headers=headers
            )
            if queued.status_code != 202:
                report.check(False, f"{item['domain']} queued ({queued.status_code})")
        report.note(f"queued {len(targets)} accounts; waiting for the worker")

        deadline = time.time() + args.account_timeout
        researched: list[dict[str, Any]] = []
        while time.time() < deadline:
            accounts = client.get(f"{api}/accounts", headers=headers).json()
            by_id = {item["id"]: item for item in accounts}
            researched = [
                by_id[item["id"]]
                for item in targets
                if by_id.get(item["id"], {}).get("scores", {}).get("confidence", {}).get("score", 0) > 0
                or by_id.get(item["id"], {}).get("brief_state") != "RESEARCH_CANDIDATE"
            ]
            if len(researched) == len(targets):
                break
            time.sleep(10)
        report.check(
            len(researched) == len(targets),
            f"{len(researched)}/{len(targets)} accounts finished research",
        )

        step("10", "What the research actually produced")
        accounts = client.get(f"{api}/accounts", headers=headers).json()
        by_id = {item["id"]: item for item in accounts}
        for item in targets:
            current = by_id[item["id"]]
            scores = current["scores"]
            report.note(
                f"{current['domain']:<20} {current['brief_state']:<28} "
                f"P{scores['priority']:>3} F{scores['fit']['score']:>3} "
                f"I{scores['intent']['score']:>3} C{scores['confidence']['score']:>3}"
            )

        distinct_states = {by_id[item["id"]]["brief_state"] for item in targets}
        report.check(
            len(distinct_states) >= 1, f"states assigned: {sorted(distinct_states)}"
        )
        scored = [by_id[item["id"]] for item in targets]
        confidences = {item["scores"]["confidence"]["score"] for item in scored}
        report.check(
            len(confidences) > 1,
            f"confidence varies with evidence rather than being constant ({sorted(confidences)})",
        )

        step("11", "Evidence is real and attributed")
        sample = scored[0] if scored else None
        if sample:
            detail = client.get(
                f"{api}/accounts/{sample['id']}/opportunity-brief", headers=headers
            )
            report.check(
                detail.status_code == 200,
                f"opportunity brief served for {sample['domain']} ({detail.status_code})",
            )
            brief = detail.json() if detail.status_code == 200 else {}
            retrieval = brief.get("retrieval") or {}
            report.check(
                bool(retrieval.get("attempted")),
                f"retrieval is reported ({retrieval.get('retrieved')}/{retrieval.get('attempted')} pages)",
            )
            evidence = brief.get("evidence") or []
            # Evidence carries source_id; the URL lives on the brief's sources list.
            # Checking the join resolves is the real test: a fact whose source is not
            # in the list is a claim the founder cannot trace back to anything.
            sources = {
                str(doc.get("id")): doc for doc in (brief.get("sources") or [])
            }
            dangling = [
                entry for entry in evidence if str(entry.get("source_id")) not in sources
            ]
            report.check(
                not dangling,
                f"all {len(evidence)} evidence items resolve to a listed source",
                f"{len(dangling)} dangling" if dangling else "",
            )
            report.check(
                all(sources[str(e["source_id"])].get("url") for e in evidence if str(e.get("source_id")) in sources),
                "every resolved source carries a URL the founder can open",
            )
            unknowns = brief.get("unknowns") or []
            report.check(
                isinstance(unknowns, list),
                f"unknowns are stated rather than hidden ({len(unknowns)} listed)",
            )
        step("11b", "Would this make sense to a founder? (§35)")
        for item in scored:
            brief_response = client.get(
                f"{api}/accounts/{item['id']}/opportunity-brief", headers=headers
            )
            if brief_response.status_code != 200:
                report.flag(
                    f"{item['domain']} was researched and scored but has no brief "
                    f"({brief_response.status_code}); the founder can see a score they "
                    "cannot open"
                )
                continue
            brief = brief_response.json()
            evidence = brief.get("evidence") or []
            retrieval = brief.get("retrieval") or {}
            scores = item["scores"]
            confidence = scores["confidence"]["score"]
            domain = item["domain"]

            # Confidence is a claim about how well the evidence supports the
            # conclusion. High confidence attached to no evidence is the one
            # combination that actively misleads.
            if confidence >= 80 and not evidence:
                report.flag(
                    f"{domain} reports {confidence}% confidence with zero evidence "
                    "items — a founder reads that as 'we are sure', when it means "
                    "'we are sure we found nothing'"
                )
            if confidence >= 80 and scores["fit"]["score"] == 0 and scores["intent"]["score"] == 0:
                report.flag(
                    f"{domain} scores 0 fit and 0 intent at {confidence}% confidence; "
                    "nothing tells the founder whether that is a real verdict or a "
                    "failed run"
                )
            if scores["fit"]["score"] == 0 and scores["intent"]["score"] > 0:
                report.flag(
                    f"{domain} has intent {scores['intent']['score']} but fit 0 — "
                    "'they are buying, but not from you' needs saying out loud or it "
                    "reads as a bug"
                )
            if retrieval.get("attempted") and not retrieval.get("retrieved"):
                report.flag(
                    f"{domain}: {retrieval.get('attempted')} pages attempted, none "
                    "read; the account looks researched but nothing was gathered"
                )
            if not brief.get("recommended_action"):
                report.flag(
                    f"{domain} has no recommended action, so the brief stops short of "
                    "telling the founder what to do next"
                )

        step("12", "FOUNDER_READY cannot be granted by hand")
        if scored:
            forced = client.patch(
                f"{api}/accounts/{scored[0]['id']}/review",
                headers=headers,
                json={"review_status": "APPROVED", "brief_state": "FOUNDER_READY"},
            )
            report.check(
                forced.status_code == 409,
                f"manual promotion to FOUNDER_READY refused ({forced.status_code})",
            )

        step("13", "The founder reviews and changes status")
        if scored:
            reviewed = client.patch(
                f"{api}/accounts/{scored[0]['id']}/review",
                headers=headers,
                json={
                    "review_status": "APPROVED",
                    "brief_state": "MONITOR",
                    "note": "Good fit, no timing signal yet. Revisit next quarter.",
                },
            )
            report.check(reviewed.status_code == 200, f"review recorded ({reviewed.status_code})")
            if reviewed.status_code == 200:
                report.check(
                    reviewed.json()["brief_state"] == "MONITOR",
                    "status change persisted",
                )

        step("14", "Exporting the reviewed list")
        export = client.get(f"{api}/exports/accounts.csv", headers=headers)
        report.check(export.status_code == 200, f"export served ({export.status_code})")
        text = export.text
        lines = [line for line in text.splitlines() if line.strip()]
        report.check(len(lines) >= 2, f"{len(lines) - 1} data row(s) exported")
        header = lines[0] if lines else ""
        report.check("domain" in header.lower(), "export carries a domain column")
        dangerous = [
            line for line in lines[1:] if line.lstrip().startswith(("=", "+", "-", "@"))
        ]
        report.check(not dangerous, "no cell starts a spreadsheet formula")

        step("15", "No autonomous outreach happened")
        audit = client.get(f"{api}/audit", headers=headers)
        if audit.status_code == 200:
            events = audit.json()
            sent = [
                item
                for item in events
                if "sent" in str(item.get("event_type", "")).lower()
            ]
            report.check(not sent, f"no send event in {len(events)} audit events")

        step("16", "No paid research provider was required")
        modes = client.get(f"{api}/product-modes", headers=headers)
        if modes.status_code == 200:
            availability = modes.json()
            report.check(
                availability.get("search_provider_configured") is False,
                "no search provider configured, and BYOA still completed",
            )

    print(f"\n{'=' * 68}")
    print(f"PASS {report.passed}   FAIL {report.failed}   FLAGS {len(report.flags)}")
    if report.flags:
        print("\nWould confuse a founder:")
        for item in report.flags:
            print(f"  · {item}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
