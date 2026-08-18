# entity-safety

Stop evidence attaching to the wrong company.

Any pipeline that gathers facts about a named entity — RAG, an agent doing
research, an enrichment job — will retrieve documents about a *different* entity
with a similar name, or about a related-but-distinct one: a parent, a
subsidiary, a product, a company that merely shares a brand token.

Similarity scoring cannot separate those, because they genuinely *are* similar.
That is the whole problem. This library answers one question, deterministically,
with a reason you can show a user:

> May this passage support a claim about this entity?

No LLM, no network, no dependencies.

## The failure it prevents

Two real companies, same brand token, same industry:

| | |
|---|---|
| `optivian.ai` | the company you are researching |
| `optivian.cloud` | a different company entirely |

A press release on `optivian.cloud` announces a $40M Series B. A naive matcher
sees the brand token, sees a plausible headline, and attaches it — and now your
system reports a funding round that the company you actually care about never
raised. Nothing errored. Nothing looked wrong. The number is just false.

```python
from entity_safety import CompanyIdentityRecord, assess_evidence_attachment

identity = CompanyIdentityRecord(
    canonical_company_name="Optivian",
    canonical_registrable_domain="optivian.ai",
    verified_official_domains=("optivian.ai",),
)

result = assess_evidence_attachment(
    identity,
    source_url="https://optivian.cloud/press/series-b",
    source_role="FIRST_PARTY",
    source_title="Optivian raises Series B",
    passage="Optivian today announced a $40M Series B.",
)

result.decision  # AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS
result.reason    # 'Different first-party domain has no verified account relationship.'
```

Refused, with a reason. The claim is not silently dropped either — you get the
relation, the inferred scope, and the confidence, so you can surface *why* to a
user instead of asking them to trust a black box.

## How it decides

Two independent gates. A passage attaches only if it clears both.

**1. Identity** — what is the relationship between source and target?

`SAME_ENTITY`, `PRODUCT_OF`, `SUBSIDIARY_OF`, `PARENT_OF`, `SISTER_BRAND`,
`REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`, `UNRELATED`, `UNKNOWN`

A relationship counts only when evidence backs it. An asserted-but-unproven
`SUBSIDIARY_OF` is treated as `UNKNOWN` — the gate fails closed.

**2. Claim scope** — what level is the claim actually about?

`COMPANY_LEVEL`, `PRODUCT_LEVEL`, `PARENT_LEVEL`, `SUBSIDIARY_LEVEL`,
`MARKET_LEVEL`, `PARTNER_LEVEL`

Keeping these separate is the point. A funding announcement about a **parent**
company is real, verified, and correctly attributed — and still not a funding
claim about the subsidiary you are researching.

Three outcomes:

| decision | meaning |
|---|---|
| `ATTACHED` | may support a claim about this entity |
| `RELATED_ENTITY_ONLY` | we know exactly who this is about, and it is not your target |
| `UNATTACHED_ENTITY_AMBIGUOUS` | we could not establish who this is about |

The last two are deliberately distinct. Collapsing them loses the difference
between a verified fact about the wrong company and an unknown.

## Install

```bash
pip install -e packages/entity-safety
```

Optional, for correct public-suffix handling (`co.uk` is a suffix, `.ai` is not):

```bash
pip install -e "packages/entity-safety[suffix]"
```

Without it, a built-in fallback covers common multi-label suffixes. With it,
the full public suffix list applies.

## Tests

17 adversarial near-miss company pairs, 22 tests (the pairs plus five
whole-matrix invariants):

```bash
python -m pytest packages/entity-safety/tests -v
```

These are the asset. They were confirmed to catch regressions by deliberately
reintroducing the naive matching this library exists to prevent — removing the
different-domain rejection fails 11 of them, including the headline invariant
that *no* unproven relationship ever produces `ATTACHED`.

See [`benchmark/`](benchmark/) to run the same cases against your own pipeline.

## Scope and limits

Honest about what this is:

- **Deterministic and conservative.** It refuses when unsure. If your use case
  prefers recall over precision, this is the wrong tool.
- **It does not discover relationships.** You supply what is known and proven;
  it decides what may attach. Populating `CompanyIdentityRecord` from the world
  is a separate problem.
- **Claim-scope inference is keyword-driven.** Pass `claim_scope` explicitly
  when you already know it.
- **Company entities.** The relationship model is corporate (parent, subsidiary,
  product, rebrand). People, places and products-as-entities are not modelled.

## Licence

MIT.
