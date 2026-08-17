from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from apps.api.app.domain.models import (
    AccountImportPayload,
)
from apps.api.app.main import app
from apps.api.app.services.byoa import (
    canonicalize_public_company_domain,
    neutralize_formula,
    product_mode_availability,
    validate_account_import,
)
from apps.api.app.services.exports import EXPORT_COLUMNS
from apps.api.app.services.entity_resolution import (
    AttachmentDecision,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
    decide_brief_state,
)


client = TestClient(app)
HEADERS = {"X-Demo-User": "demo-user"}


def test_byoa_is_available_without_exa_or_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    availability = product_mode_availability()
    assert availability.byoa_core == "AVAILABLE"
    assert (
        availability.autonomous_discovery_experimental
        == "CONFIGURATION_REQUIRED"
    )
    assert availability.search_provider_configured is False
    assert availability.primary_provider == "NONE"


def test_discovery_requires_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    product_id = client.get("/api/v1/bootstrap", headers=HEADERS).json()["product"]["id"]
    response = client.post(
        "/api/v1/research-runs",
        headers=HEADERS,
        params={
            "product_id": product_id,
            "product_mode": "AUTONOMOUS_DISCOVERY_EXPERIMENTAL",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CONFIGURATION_REQUIRED"


def test_byoa_run_defaults_without_search_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    product_id = client.get("/api/v1/bootstrap", headers=HEADERS).json()["product"]["id"]
    response = client.post(
        "/api/v1/research-runs",
        headers=HEADERS,
        params={"product_id": product_id},
    )
    assert response.status_code == 202
    assert response.json()["product_mode"] == "BYOA_CORE"


def test_csv_upload_validation_and_formula_neutralisation() -> None:
    csv_text = (
        "company_name,domain,notes,owner,tags\n"
        "Safe Co,safe-company.com,=cmd,+owner,@priority|normal\n"
    )
    result = validate_account_import(
        AccountImportPayload(csv_text=csv_text, import_source="CSV_UPLOAD")
    )
    assert not result.issues
    assert result.accepted[0].notes == "'=cmd"
    assert result.accepted[0].owner == "'+owner"
    assert result.accepted[0].tags == ["'@priority", "normal"]


def test_malformed_csv_is_rejected() -> None:
    result = validate_account_import(
        AccountImportPayload(csv_text='company_name,domain\n"Acme,acme.com')
    )
    assert result.accepted == []
    assert result.issues[0].code == "MALFORMED_CSV"


def test_csv_requires_documented_headers() -> None:
    result = validate_account_import(
        AccountImportPayload(csv_text="name,url\nAcme,acme.com")
    )
    assert result.accepted == []
    assert result.issues[0].code == "MISSING_HEADERS"


def test_pasted_domains_are_canonicalised_and_deduplicated() -> None:
    result = validate_account_import(
        AccountImportPayload(
            pasted_domains=(
                "BiggerWide, https://www.biggerwide.com/about\n"
                "https://biggerwide.com/\n"
                "CloudSEK, cloudsek.com"
            )
        )
    )
    assert [item.domain for item in result.accepted] == [
        "biggerwide.com",
        "cloudsek.com",
    ]
    assert result.duplicate_domains == ["biggerwide.com"]


@pytest.mark.parametrize(
    "domain",
    [
        "localhost",
        "http://127.0.0.1",
        "http://10.0.0.4",
        "file:///etc/passwd",
        "https://user:pass@example.com",
        "https://linkedin.com/company/example",
        "=HYPERLINK(\"https://example.com\")",
    ],
)
def test_unsafe_company_domains_are_rejected(domain: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_public_company_domain(domain)


def test_imported_and_discovered_provenance_are_separate() -> None:
    response = client.post(
        "/api/v1/accounts/import",
        headers=HEADERS,
        json={
            "accounts": [
                {
                    "company_name": "BYOA Provenance Test",
                    "domain": "byoa-provenance-test.com",
                }
            ],
            "import_source": "API",
        },
    )
    assert response.status_code == 201
    account_id = response.json()["imported"][0]["id"]
    accounts = client.get("/api/v1/accounts", headers=HEADERS).json()
    imported = next(item for item in accounts if item["id"] == account_id)
    discovered = next(item for item in accounts if item["id"] != account_id)
    assert imported["provenance"] == "IMPORTED"
    assert imported["import_source"] == "SINGLE"
    assert discovered["provenance"] == "DISCOVERED"
    assert discovered["import_source"] is None


def test_cross_company_and_related_brand_claim_scope_are_rejected() -> None:
    identity = CompanyIdentityRecord(
        canonical_company_name="Target Cloud",
        canonical_registrable_domain="target.cloud",
        verified_official_domains=("target.cloud",),
        identity_confidence=0.99,
    )
    ambiguous = assess_evidence_attachment(
        identity,
        source_url="https://target.ai/news",
        source_role="FIRST_PARTY",
        source_title="Target AI news",
        passage="Target AI launched a product.",
        claim_scope=ClaimScope.PRODUCT_LEVEL,
    )
    assert ambiguous.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS

    related_identity = CompanyIdentityRecord(
        canonical_company_name="Parent Co",
        canonical_registrable_domain="parent.co",
        verified_official_domains=("parent.co",),
        relationships=(
            VerifiedEntityRelationship(
                subject_domain="product.co",
                object_domain="parent.co",
                relation=EntityRelation.PRODUCT_OF,
                evidence_ids=("relationship-evidence",),
            ),
        ),
        identity_confidence=0.99,
    )
    incompatible = assess_evidence_attachment(
        related_identity,
        source_url="https://product.co/launch",
        source_role="FIRST_PARTY",
        source_title="Product launch",
        passage="Product Co launched a feature.",
        claim_scope=ClaimScope.PARENT_LEVEL,
    )
    assert incompatible.decision == AttachmentDecision.RELATED_ENTITY_ONLY


def test_brief_states_cover_competitor_no_signal_identity_and_founder_ready() -> None:
    assert (
        decide_brief_state(
            identity_verified=True,
            unresolved_identity_warnings=(),
            qualification_status="DISQUALIFIED",
            has_supported_icp_fact=True,
            has_actionable_signal=True,
            supported_important_claims=True,
            direct_competitor_conflict=True,
        ).value
        == "DO_NOT_TARGET"
    )
    assert (
        decide_brief_state(
            identity_verified=True,
            unresolved_identity_warnings=(),
            qualification_status="QUALIFIED",
            has_supported_icp_fact=True,
            has_actionable_signal=False,
            supported_important_claims=True,
            direct_competitor_conflict=False,
        ).value
        == "MONITOR"
    )
    assert (
        decide_brief_state(
            identity_verified=False,
            unresolved_identity_warnings=("same-name ambiguity",),
            qualification_status="QUALIFIED_WITH_UNCERTAINTY",
            has_supported_icp_fact=False,
            has_actionable_signal=False,
            supported_important_claims=False,
            direct_competitor_conflict=False,
        ).value
        == "IDENTITY_REVIEW_REQUIRED"
    )
    assert (
        decide_brief_state(
            identity_verified=True,
            unresolved_identity_warnings=(),
            qualification_status="QUALIFIED",
            has_supported_icp_fact=True,
            has_actionable_signal=True,
            supported_important_claims=True,
            direct_competitor_conflict=False,
        ).value
        == "FOUNDER_READY"
    )


def test_safe_export_contract_and_formula_neutralisation() -> None:
    assert neutralize_formula("=SUM(1,1)") == "'=SUM(1,1)"
    response = client.post(
        "/api/v1/accounts/import",
        headers=HEADERS,
        json={
            "accounts": [
                {
                    "company_name": "Safe Export Co",
                    "domain": "safe-export-co.com",
                }
            ],
            "import_source": "API",
        },
    )
    account_id = response.json()["imported"][0]["id"]
    reviewed = client.patch(
        f"/api/v1/accounts/{account_id}/review",
        headers=HEADERS,
        json={"review_status": "APPROVED"},
    )
    assert reviewed.status_code == 200
    exported = client.get("/api/v1/exports/accounts.csv", headers=HEADERS)
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    # Blueprint section 19 names: `domain` and `state`, plus the owner field that
    # was missing entirely. Asserted against the shared definition so the two
    # export surfaces cannot drift apart again.
    row = next(item for item in rows if item["domain"] == "safe-export-co.com")
    assert set(row) == set(EXPORT_COLUMNS)
    assert row["review_status"] == "APPROVED"
    assert row["state"] == "RESEARCH_CANDIDATE"


def test_non_founder_ready_campaign_cannot_be_edited_or_approved() -> None:
    response = client.post(
        "/api/v1/accounts/import",
        headers=HEADERS,
        json={
            "accounts": [
                {
                    "company_name": "Evidence Gate Control",
                    "domain": "evidence-gate-control.com",
                }
            ],
            "import_source": "API",
        },
    )
    account_id = response.json()["imported"][0]["id"]
    brief = client.get(
        f"/api/v1/accounts/{account_id}/opportunity-brief",
        headers=HEADERS,
    ).json()
    assert brief["brief_state"] == "RESEARCH_CANDIDATE"
    campaign_id = brief["campaign"]["id"]
    edited = client.patch(
        f"/api/v1/campaigns/{campaign_id}",
        headers=HEADERS,
        json={"action": "edit", "subject": "Unsafe draft"},
    )
    approved = client.patch(
        f"/api/v1/campaigns/{campaign_id}",
        headers=HEADERS,
        json={"action": "approve"},
    )
    assert edited.status_code == 409
    assert approved.status_code == 409
