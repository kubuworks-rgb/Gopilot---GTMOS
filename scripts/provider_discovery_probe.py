from __future__ import annotations

import asyncio

from services.research_gateway.app.adapters.search import SearchAdapter
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.schemas import SearchRequest


QUERIES = (
    "India B2B SaaS customer onboarding companies official websites",
    "India compliance SaaS companies official websites",
    "India SaaS spend management companies official websites",
    "India revenue intelligence SaaS companies official websites",
    "India product analytics SaaS companies official websites",
    "India HR SaaS companies official websites",
    "India logistics SaaS companies official websites",
    "India developer tools SaaS companies official websites",
    "Bengaluru B2B SaaS enterprise software official company website",
    "Mumbai B2B cloud software official company website",
    "Pune enterprise SaaS platform official company website",
    "Gurugram B2B SaaS official company website",
    "India ecommerce SaaS platform official company website",
    "India fintech SaaS platform official company website",
)


async def main() -> None:
    adapter = SearchAdapter()
    for query in QUERIES:
        try:
            results, diagnostics = await adapter.search(
                SearchRequest(
                    workspace_id="supportpilot-probe",
                    research_run_id="supportpilot-probe",
                    query=query,
                    limit=5,
                    purpose="account_discovery",
                )
            )
        except GatewayAdapterError as exc:
            print(f"\nQUERY: {query}\nERROR: {exc.code} - {exc.safe_message}")
            continue
        print(f"\nQUERY: {query}")
        print(f"RESULTS: {len(results)}/{diagnostics.results_before_filter}")
        for item in results:
            print(f"- {item.title} | {item.url}")


if __name__ == "__main__":
    asyncio.run(main())
