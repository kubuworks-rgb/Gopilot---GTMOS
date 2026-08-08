from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AttributePrecision(StrEnum):
    EXACT = "EXACT"
    RANGE = "RANGE"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FirmographicAttribute:
    name: str
    value: str | None
    precision: AttributePrecision
    confidence: float
    source_ids: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class CompanyFirmographics:
    employee_count: FirmographicAttribute
    geography: FirmographicAttribute
    business_model: FirmographicAttribute
    industry: FirmographicAttribute
    provider: str


class CompanyFirmographicProvider(Protocol):
    name: str

    async def enrich(
        self,
        *,
        company_name: str,
        domain: str,
        public_text: str,
        source_ids: tuple[str, ...],
    ) -> CompanyFirmographics: ...


class PublicEvidenceFirmographicProvider:
    """Company-level public-evidence fallback; never infers private-person data."""

    name = "public_evidence"

    async def enrich(
        self,
        *,
        company_name: str,
        domain: str,
        public_text: str,
        source_ids: tuple[str, ...],
    ) -> CompanyFirmographics:
        del company_name, domain
        text = public_text.lower()
        exact = re.search(
            r"\b(?:employs|team of|workforce of|we employ)\s+"
            r"(\d{1,5})\+?\s+(?:employees|people|team members)\b",
            text,
        )
        ranged = re.search(
            r"\b(\d{1,5})\s*[-–]\s*(\d{1,5})\s+employees\b",
            text,
        )
        if exact:
            employees = FirmographicAttribute(
                "employee_count",
                exact.group(1),
                AttributePrecision.EXACT,
                0.90,
                source_ids,
                "Explicit company-level employee statement in public evidence.",
            )
        elif ranged:
            employees = FirmographicAttribute(
                "employee_count",
                f"{ranged.group(1)}-{ranged.group(2)}",
                AttributePrecision.RANGE,
                0.82,
                source_ids,
                "Explicit employee range in public evidence.",
            )
        else:
            employees = FirmographicAttribute(
                "employee_count",
                None,
                AttributePrecision.UNKNOWN,
                0,
                (),
                "No compatible company-level employee evidence.",
            )
        india_terms = (
            "india",
            "bengaluru",
            "bangalore",
            "hyderabad",
            "pune",
            "mumbai",
            "gurugram",
            "chennai",
            "noida",
        )
        geography = FirmographicAttribute(
            "geography",
            "India" if any(item in text for item in india_terms) else None,
            (
                AttributePrecision.EXACT
                if any(item in text for item in india_terms)
                else AttributePrecision.UNKNOWN
            ),
            0.82 if any(item in text for item in india_terms) else 0,
            source_ids if any(item in text for item in india_terms) else (),
            "Location terms found in public company evidence."
            if any(item in text for item in india_terms)
            else "Geography remains unknown.",
        )
        software = any(
            item in text
            for item in (
                "b2b saas",
                "software as a service",
                "enterprise software",
                "software platform",
                "cloud platform",
            )
        )
        business_model = FirmographicAttribute(
            "business_model",
            "B2B SaaS" if software else None,
            AttributePrecision.ESTIMATED if software else AttributePrecision.UNKNOWN,
            0.72 if software else 0,
            source_ids if software else (),
            "Public product language is consistent with B2B SaaS."
            if software
            else "Business model remains unknown.",
        )
        return CompanyFirmographics(
            employee_count=employees,
            geography=geography,
            business_model=business_model,
            industry=FirmographicAttribute(
                "industry",
                "Software" if software else None,
                AttributePrecision.ESTIMATED if software else AttributePrecision.UNKNOWN,
                0.70 if software else 0,
                source_ids if software else (),
                "Public product language supports software classification."
                if software
                else "Industry remains unknown.",
            ),
            provider=self.name,
        )
