# Building your own GTM agent on GoPilot

This repo is a working evidence pipeline, not a framework you configure. The
useful thing to take from it is the part that is genuinely hard to get right:
turning a company domain into attributed, identity-checked evidence and a score
you can defend. Most of what you will want to change sits behind five seams,
listed below with the exact file and function.

Read [ARCHITECTURE.md](../ARCHITECTURE.md) first for the one-page shape. This
document is about where to put your hands.

> **On the word "agent."** GoPilot never sends anything and never acts without a
> human approving. That is enforced, not conventional: `FOUNDER_READY` cannot be
> set by an API call (returns 409), and outbound sending does not exist in the
> codebase. If you are building something that *does* act autonomously, this repo
> is the research-and-evidence half of it — the half that decides *whether* an
> account is worth acting on. Wire your own action layer on top of the export or
> the API; don't try to make the pipeline itself act.

---

## The pipeline, in one line

```
import → validate domain → identity gate → fetch official pages → extract
evidence → attach or reject per entity/scope → score → compose brief → human
review → export
```

Each arrow is a function you can replace. The order is load-bearing: evidence is
attached *before* scoring, and scoring is deterministic *after* attachment, so a
model can never move a number.

---

## Seam 1 — Add a research source

**Where:** `services/research_gateway/app/adapters/`
**Protocol:** [`adapters/base.py`](../services/research_gateway/app/adapters/base.py) — `health()`, `search()`, `fetch()`
**Register in:** [`services/research_gateway/app/main.py:38`](../services/research_gateway/app/main.py) (module-level instances)

The gateway is the *only* component allowed to make outbound HTTP calls. That is
a security boundary, not an organizational one: it owns URL validation, redirect
re-validation, IP pinning against DNS rebinding, content-type allowlisting, and
size caps. An adapter that fetches directly with `httpx` bypasses all of it.

Use [`adapters/rss.py`](../services/research_gateway/app/adapters/rss.py) as the
template — it is the smallest complete one, and it correctly delegates actual
retrieval to `WebPageAdapter` rather than reimplementing the safety checks.

```python
class MyAdapter:
    name = "mysource"

    async def health(self) -> AdapterHealth: ...
    async def fetch(self, request: FetchRequest) -> SourceDocumentInput: ...
```

Always route retrieval through `WebPageAdapter` or `validate_public_url()`. If
your source needs a credential, it must degrade to `CONFIGURATION_REQUIRED`
rather than failing the run — the no-key BYOA path must keep working without it.

## Seam 2 — Change the scoring formula

**Where:** [`apps/api/app/services/scoring.py`](../apps/api/app/services/scoring.py)
**Main entry:** `score_account()` — pure function, no I/O, no DB, no model call
**Called from:** [`live_research.py:2808`](../apps/api/app/services/live_research.py) (live) and `repositories/fixture.py` (demo)

Because it is pure, you can change weights and unit-test the result without
standing anything up. Three rules the existing tests will hold you to:

- **Scores stay deterministic.** No LLM may produce a final number. This is
  checked by `test_scoring_is_deterministic_and_fit_is_separate_from_intent`.
- **Unknown is not zero.** Pass `None` for a factor you could not determine, not
  `0`. `_breakdown_missing_aware` excludes it and renormalizes the remaining
  weights; if *every* factor is unknown the dimension is marked
  `determined=False` and `_priority_from` excludes the whole dimension. Passing
  `0` for "we don't know" silently states "we checked and it's bad" — that exact
  bug cost an account more than half its priority and is documented in
  [LIVE_E2E_FINDINGS.md §2](qa/LIVE_E2E_FINDINGS.md).
- **Every component carries its evidence IDs.** A number with no traceable
  support is the thing this project exists to avoid.

Adding a fourth dimension means touching `AccountScores`
([`domain/models.py`](../apps/api/app/domain/models.py)), the web `Scores` type
([`apps/web/lib/types.ts`](../apps/web/lib/types.ts)), and the export columns
([`services/exports.py`](../apps/api/app/services/exports.py)). The typechecker
finds all three for you.

## Seam 3 — Change what counts as valid evidence

**Where:** [`apps/api/app/services/entity_resolution.py`](../apps/api/app/services/entity_resolution.py)
**Main entry:** `assess_evidence_attachment()` — the dual gate
**Called from:** [`live_research.py:2548`](../apps/api/app/services/live_research.py)

This is the part most worth stealing. Every candidate passage is judged on two
independent axes before it may support a claim:

- **Identity** — 10 relations (`SAME_ENTITY`, `SUBSIDIARY_OF`, `ACQUIRED_BY`,
  `SISTER_BRAND`, `UNRELATED`, …) in `EntityRelation`
- **Claim scope** — 6 scopes in `ClaimScope`, via `infer_claim_scope()`

A funding claim about a parent company is not a funding claim about the
subsidiary you are researching. `claim_scope_is_compatible()` encodes which
relation may carry which scope. Loosen it and
`packages/entity-safety/tests/test_confusable_pairs.py` (17 real near-miss
company pairs, covered by 22 tests) will tell you what you broke — removing the
different-domain rejection fails 11 of them.

Rejected evidence is surfaced to the user with its reason, not silently dropped
(`RejectedEvidencePanel` in the web app). Keep that if you change this — the
value is in showing your work.

## Seam 4 — Change qualification and states

**Where:** [`entity_resolution.py`](../apps/api/app/services/entity_resolution.py) — `decide_brief_state()`
**States:** `FOUNDER_READY`, `RESEARCH_CANDIDATE`, `MONITOR`,
`IDENTITY_REVIEW_REQUIRED`, `DO_NOT_TARGET`

`FOUNDER_READY` is the gate that permits outreach copy to exist at all. It is
earned from evidence, never granted: a direct `PATCH` attempting to set it
returns 409, verified live. If you add a state, decide explicitly whether it may
expose outreach copy, and keep the 409 behaviour for anything that does.

## Seam 5 — Add an API endpoint

**Where:** [`apps/api/app/api/routes.py`](../apps/api/app/api/routes.py) (fixture) **and**
[`live_routes.py`](../apps/api/app/api/live_routes.py) (live)

There are two routers implementing one contract against different repositories —
fixture (in-memory, synchronous) and Postgres (async, session-injected).
`test_router_contract_parity.py` fails the build if they drift, and it exists
because they *had* drifted: the export column lists diverged, and later an
invite-gate check was added to only one of them, letting a validly-signed but
uninvited identity through in fixture mode.

Practically: add to both, or add to `live_routes.py` only and declare it in
`LIVE_ONLY` with a reason. Shared logic belongs in `services/` and is imported
by both — that is why `exports.py` exists.

---

## The four rules that are not negotiable

These are enforced by tests, and a PR that breaks them will fail CI regardless of
how good the rest is. They are also in [CONTRIBUTING.md](../CONTRIBUTING.md).

1. **Deterministic scoring.** LLMs summarize; they never produce a number the
   product acts on.
2. **Evidence-backed claims.** A material claim carries evidence IDs resolving to
   a real passage in a real retrieved document, or it is marked as a hypothesis.
3. **Unknown ≠ false.** Missing information renormalizes; it never scores as a
   confident zero.
4. **No autonomous outbound action.** Nothing sends. Human approval is a
   structural gate, not a config flag.

If your project genuinely needs to break one of these, fork rather than patch
around the tests — they are the reason the numbers here mean anything.

---

## Verifying your changes

```bash
npm run test        # 474 Python, 43 web, 11 CLI
npm run lint
npm run typecheck
```

Against a real stack, with no API keys:

```bash
docker compose -f deploy/docker-compose.dev-infra.yml up -d
npm run dev:live
python scripts/verify_e2e_scenario.py
```

`verify_e2e_scenario.py` walks the whole scenario against real websites and
prints `PASS`/`FAIL` per step, plus `FLAG` for things that pass technically but
would confuse a user. It is the honest check: a green unit suite did not catch
the scoring bug in §2 of the findings doc, and this did.
