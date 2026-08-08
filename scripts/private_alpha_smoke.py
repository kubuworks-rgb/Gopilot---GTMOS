"""End-to-end private-alpha smoke test against real infrastructure.

Exercises the BYOA journey through the running API: workspace, product, run,
import, research, brief, review, export. Real PostgreSQL, real Redis, real worker,
real HTTP fetches of real company websites. No fixtures and no mocks -- a green
mocked run would tell an operator nothing about whether the deployment works.

    python scripts/private_alpha_smoke.py
    python scripts/private_alpha_smoke.py --api-base http://127.0.0.1:8000/api/v1

Exit code 0 means the deployment is serving the core product correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import httpx


DEFAULT_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000/api/v1")

# Stable, well-known company sites. Chosen because they are real, publicly
# reachable, and unlikely to disappear -- not because they are prospects.
ACCOUNTS = [
    {"company_name": "Python Software Foundation", "domain": "python.org"},
    {"company_name": "SQLAlchemy", "domain": "sqlalchemy.org"},
]


class SmokeFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {message}")
    if not condition:
        raise SmokeFailure(message)


async def wait_for(
    client: httpx.AsyncClient, path: str, predicate, *, timeout: float, label: str
):
    """Poll until `predicate` holds. Returns the payload, or raises on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last: object = None
    while loop.time() < deadline:
        response = await client.get(path)
        response.raise_for_status()
        last = response.json()
        if predicate(last):
            return last
        await asyncio.sleep(2)
    raise SmokeFailure(f"Timed out waiting for {label}; last payload: {last}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_BASE)
    parser.add_argument(
        "--user",
        default=os.getenv("SMOKE_USER", f"smoke-{uuid.uuid4().hex[:8]}"),
        help="an invited subject when PRIVATE_ALPHA_ENABLED=true",
    )
    parser.add_argument("--research-timeout", type=float, default=240.0)
    parser.add_argument(
        "--keep", action="store_true", help="keep the workspace after the run"
    )
    args = parser.parse_args()

    headers = {"X-Demo-User": args.user}
    workspace_id: str | None = None

    async with httpx.AsyncClient(
        base_url=args.api_base, headers=headers, timeout=60.0
    ) as client:
        print("\n[0] Invite gate")
        async with httpx.AsyncClient(
            base_url=args.api_base,
            headers={"X-Demo-User": f"uninvited-{uuid.uuid4().hex[:8]}"},
            timeout=30.0,
        ) as uninvited:
            response = await uninvited.post(
                "/workspaces", json={"name": "Should Not Exist"}
            )
            if response.status_code == 403:
                check(True, "uninvited identity refused (private alpha enforced)")
            else:
                print(
                    "  SKIP  invite gate is off in this deployment "
                    f"(got {response.status_code})"
                )

        print(f"\n[1] Workspace  (actor {args.user})")
        response = await client.post("/workspaces", json={"name": "Smoke Workspace"})
        if response.status_code == 403:
            raise SmokeFailure(
                f"{args.user!r} is not on the invite list. Re-run with "
                "--user <an invited subject>, or set SMOKE_USER. "
                "See PRIVATE_ALPHA_ALLOWED_SUBJECTS in your env file."
            )
        check(response.status_code == 201, f"workspace created ({response.status_code})")
        workspace_id = response.json()["id"]
        client.headers["X-Workspace-Id"] = workspace_id
        print(f"      workspace {workspace_id}")

        print("\n[2] Product profile")
        response = await client.post(
            "/products",
            json={
                "company_name": "GoPilot Smoke",
                "website": "https://example.org",
                "product": "Evidence-backed GTM research for founders.",
                "target_market": "B2B SaaS companies evaluating developer tooling.",
            },
        )
        check(response.status_code == 201, f"product created ({response.status_code})")
        product_id = response.json()["id"]

        print("\n[3] Product modes without a search provider")
        response = await client.get("/product-modes")
        modes = response.json()
        check(modes["byoa_core"] == "AVAILABLE", "BYOA_CORE is AVAILABLE")
        check(
            modes["autonomous_discovery_experimental"] == "CONFIGURATION_REQUIRED",
            "autonomous discovery is CONFIGURATION_REQUIRED",
        )
        check(
            modes["search_provider_configured"] is False,
            "no search provider is configured",
        )

        print("\n[4] BYOA run")
        response = await client.post(
            f"/research-runs?product_id={product_id}&product_mode=BYOA_CORE"
        )
        check(response.status_code == 202, f"run created ({response.status_code})")
        run = response.json()
        check(run["product_mode"] == "BYOA_CORE", "run is BYOA_CORE")
        check(
            run["current_stage"] == "accounts_import_ready",
            f"run is import-ready ({run['current_stage']})",
        )

        print("\n[5] Import validation refuses unsafe input")
        response = await client.post(
            "/account-imports/validate",
            json={
                "accounts": [
                    {"company_name": "Localhost", "domain": "localhost"},
                    {"company_name": "Metadata", "domain": "169.254.169.254"},
                    {"company_name": "Directory", "domain": "linkedin.com"},
                    {"company_name": "Good Co", "domain": "python.org"},
                ],
                "import_source": "API",
            },
        )
        validation = response.json()
        codes = {issue["code"] for issue in validation["issues"]}
        check(len(validation["accepted"]) == 1, "only the safe domain is accepted")
        check(
            {"PRIVATE_DESTINATION", "IP_DESTINATION", "NON_COMPANY_DOMAIN"} <= codes,
            f"unsafe domains rejected with reasons ({sorted(codes)})",
        )

        print("\n[6] Import accounts")
        response = await client.post(
            "/accounts/import",
            json={"accounts": ACCOUNTS, "import_source": "API"},
        )
        check(response.status_code == 201, f"import accepted ({response.status_code})")
        imported = response.json()["imported"]
        check(len(imported) == len(ACCOUNTS), f"{len(imported)} accounts imported")
        for item in imported:
            check(
                item["provenance"] == "IMPORTED",
                f"{item['canonical_domain']} marked IMPORTED",
            )
        account_ids = [item["id"] for item in imported]

        print("\n[7] Duplicate import is rejected, not silently merged")
        response = await client.post(
            "/accounts/import", json={"accounts": ACCOUNTS, "import_source": "API"}
        )
        duplicates = response.json()["duplicate_domains"]
        check(len(duplicates) == len(ACCOUNTS), f"duplicates reported: {duplicates}")

        print("\n[8] Research through the worker (real network fetches)")
        for account_id in account_ids:
            response = await client.post(f"/accounts/{account_id}/research")
            check(response.status_code == 202, f"queued {account_id[:8]}")

        def researched(payload: object) -> bool:
            assert isinstance(payload, list)
            return all(
                item["domain_validation"] != "CANONICALIZED_UNVERIFIED"
                for item in payload
                if item["id"] in account_ids
            )

        accounts = await wait_for(
            client,
            "/accounts",
            researched,
            timeout=args.research_timeout,
            label="official-site research to finish",
        )
        assert isinstance(accounts, list)
        researched_accounts = [a for a in accounts if a["id"] in account_ids]
        for account in researched_accounts:
            print(
                f"      {account['domain']:20} state={account['brief_state']:24}"
                f" fit={account['scores']['fit']['score']:3}"
                f" intent={account['scores']['intent']['score']:3}"
                f" conf={account['scores']['confidence']['score']:3}"
            )

        print("\n[9] Briefs are evidence-backed")
        for account in researched_accounts:
            response = await client.get(
                f"/accounts/{account['id']}/opportunity-brief"
            )
            check(response.status_code == 200, f"brief for {account['domain']}")
            brief = response.json()
            check(
                len(brief["sources"]) > 0,
                f"{account['domain']} has {len(brief['sources'])} source document(s)",
            )
            identity = brief["verified_identity"]
            official = identity.get("verified_official_domains") or []
            check(
                account["domain"] in [str(d) for d in official]
                or brief["brief_state"] == "IDENTITY_REVIEW_REQUIRED",
                f"{account['domain']} identity verified or flagged for review",
            )
            # Cross-company contamination: no source may come from another
            # imported account's domain.
            others = {a["domain"] for a in researched_accounts} - {account["domain"]}
            source_hosts = " ".join(str(s["canonical_url"]) for s in brief["sources"])
            check(
                not any(other in source_hosts for other in others),
                f"{account['domain']} carries no cross-company evidence",
            )
            if brief["brief_state"] != "FOUNDER_READY":
                # A draft row may exist as a research checkpoint. What must hold is
                # that it is never approved and cannot be approved; step 10 proves
                # the API refuses. The UI hides the editor entirely.
                check(
                    brief["campaign"]["status"] == "draft",
                    f"{account['domain']} draft is unapproved (not FOUNDER_READY)",
                )

        print("\n[10] Outreach stays gated")
        non_ready = [
            a for a in researched_accounts if a["brief_state"] != "FOUNDER_READY"
        ]
        if non_ready:
            response = await client.get(
                f"/accounts/{non_ready[0]['id']}/opportunity-brief"
            )
            campaign_id = response.json()["campaign"]["id"]
            response = await client.patch(
                f"/campaigns/{campaign_id}", json={"action": "approve"}
            )
            check(
                response.status_code == 409,
                f"approving a non-ready draft is refused ({response.status_code})",
            )

        print("\n[11] FOUNDER_READY cannot be granted by hand")
        response = await client.patch(
            f"/accounts/{account_ids[0]}/review",
            json={"review_status": "APPROVED", "brief_state": "FOUNDER_READY"},
        )
        check(
            response.status_code == 409,
            f"manual promotion refused ({response.status_code})",
        )

        print("\n[12] Review and export")
        response = await client.patch(
            f"/accounts/{account_ids[0]}/review", json={"review_status": "APPROVED"}
        )
        check(response.status_code == 200, "account approved for export")

        response = await client.get("/exports/accounts.csv")
        check(response.status_code == 200, "export served")
        body = response.text
        rows = [line for line in body.splitlines() if line.strip()]
        check(len(rows) == 2, f"only approved accounts exported ({len(rows) - 1} row)")
        check("company_name,canonical_domain" in rows[0], "export header is correct")
        for secret in ("Authorization", "Bearer ", "EXA_API_KEY", "password"):
            check(secret not in body, f"export leaks no {secret!r}")

        print("\n[13] Tenant isolation")
        async with httpx.AsyncClient(
            base_url=args.api_base,
            headers={"X-Demo-User": "intruder", "X-Workspace-Id": workspace_id},
            timeout=30.0,
        ) as intruder:
            response = await intruder.get("/bootstrap")
            check(
                response.status_code in {403, 404},
                f"another user cannot reach this workspace ({response.status_code})",
            )

        print("\n[14] Cleanup")
        if args.keep:
            print(f"      keeping workspace {workspace_id}")
        else:
            print(f"      workspace {workspace_id} left for inspection; remove with:")
            print(
                "      python scripts/delete_workspace_data.py "
                f"--workspace-id {workspace_id} --confirm"
            )

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SmokeFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
