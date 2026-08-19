# Three bugs that produce confident, wrong answers

Every one of these shipped. None of them crashed, threw, or logged a warning.
Each produced a plausible number or an allowed request, and each was found by
running the system rather than by reading it.

They are worth writing down because none is exotic. If you are building a
retrieval pipeline, an agent that gathers facts, or any service with more than
one code path to the same resource, you probably have at least one of these
right now.

---

## 1. Evidence attaching to the wrong company

Two companies. Same brand token. Different TLD.

```
optivian.ai      the company you are researching
optivian.cloud   a different company entirely
```

A press release on `optivian.cloud` announces a $40M Series B. A retrieval
pipeline scores it against the target: brand token matches, industry matches,
the headline is exactly the kind of thing you were looking for. High similarity.
Attach.

Now your system reports a funding round that the company you actually care
about never raised. Nothing errored. The number is simply false, and it is false
in a way that survives review, because every individual step behaved
reasonably.

**Why similarity cannot fix this.** The two documents *are* similar. That is not
a scoring bug to be tuned away — it is the ground truth. Turning the threshold
up loses real evidence; turning it down admits more contamination. The axis is
wrong.

The fix is to stop asking "how similar is this?" and start asking two separate
questions:

1. **Identity** — what is the relationship between the source and the target?
2. **Claim scope** — what level is the claim actually about?

Ten relationship types (`SAME_ENTITY`, `PRODUCT_OF`, `SUBSIDIARY_OF`,
`PARENT_OF`, `SISTER_BRAND`, `REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`,
`UNRELATED`, `UNKNOWN`) against six claim scopes. A passage attaches only if it
clears both gates.

Keeping them separate is the whole point. A funding announcement about a
**parent** company is real, verified, and correctly attributed — and still not a
funding claim about the subsidiary you are researching. Collapse the two
questions into one score and that distinction is unrecoverable.

Two rules matter more than the taxonomy:

- **Unproven relationships fail closed.** An asserted-but-unevidenced
  `SUBSIDIARY_OF` is treated as `UNKNOWN`.
- **"Different company" and "don't know" are different rejections.**
  `RELATED_ENTITY_ONLY` means *we know exactly who this is about, and it is not
  your target*. `UNATTACHED_ENTITY_AMBIGUOUS` means *we could not establish who
  this is about*. Collapsing them throws away the difference between a verified
  fact about the wrong company and an unknown.

### Proving the protection actually protects

A test suite that passes tells you nothing about whether it would catch the bug
it was written for. So: reintroduce the defect and confirm the suite goes red.

Removing the different-domain rejection — the original Optivian defect — fails
**11 of 22 tests**, including the invariant that no unproven relationship ever
produces `ATTACHED`.

A first attempt at breaking it is worth reporting too, because it failed
usefully: switching whole-token name matching to substring matching broke
**nothing**. The fixtures differ by *domain*, not by name shape. That is a real
gap in the suite's coverage, found by trying to break it rather than by reading
it.

The cases are published as a benchmark you can run against your own pipeline,
in any language — emit `{"case-id": "DECISION"}` and score it. As calibration, a
naive brand-token matcher scores **17.6%, with 14 contaminations out of 17
cases**.

It is 17 cases. That is small, and it is a starting point rather than a
standard.

---

## 2. Unknown silently becoming a confident zero

A scoring function had a guard for missing data. When one factor of a dimension
was unknown, it was dropped and the remaining weights renormalised, so an
absence of information never counted as a negative.

Then every factor of a dimension was unknown, and it fell through to this:

```python
if known_weight <= 0:
    return ScoreBreakdown(score=0, components=[])
```

Score zero, empty component list. The exact defect the function existed to
prevent — one level up.

Downstream, that zero was multiplied into a priority score:

```python
priority = round((fit.score * 0.55 + intent.score * 0.45) * confidence.score / 100)
```

A live run against 20 real companies caught it. For `fly.io` — strong intent,
high confidence, fit *never determined*:

| | |
|---|---|
| As shipped | `(0×0.55 + 70×0.45) × 0.95` = **30** |
| Fit excluded, intent renormalised | `70 × 0.95` = **66** |

Ranked less than half as urgent as its own evidence supported. And the user
could not tell: another account scored fit 0 because it had genuinely been
evaluated and found to be a poor fit. Both rendered as "0". One was a verdict,
the other was an absence of a verdict, and nothing distinguished them.

**The general shape:** a sentinel value that is indistinguishable from a real
measurement. `0`, `""`, `false`, and `0.0` all look like answers. If your model
cannot say "not determined" as a distinct state from "determined to be zero",
something downstream will eventually treat the first as the second — and it will
be arithmetic that does it, quietly, not a branch you can grep for.

The fix was to make the absence representable (`determined: bool`), then apply
the *same* missing-aware composition one level up: exclude the undetermined
dimension and renormalise the remainder, rather than multiplying by a phantom
zero.

Re-verified by tearing the stack down, rebuilding from an empty database, and
re-running against real websites: `fly.io` came back at priority **66**.

Worth noting what was *not* fixed: a "Fit 60+" filter still excludes an
undetermined account rather than treating it as its own category. Same class of
bug, one layer out.

---

## 3. Authentication mistaken for authorization

Two API routers implemented the same product surface against different storage
backends — one in-memory for local development, one Postgres for production.
Shared logic lived in shared modules. Reasonable structure.

An invite-gate was added to restrict a deployment to invited identities. It was
added to one router.

The other one authenticated correctly — a real, valid, cryptographically-sound
token — and then never asked whether that identity was *allowed*. Anyone who
could obtain a validly-signed token was in.

**The shape of the mistake is the interesting part.** Authentication and
authorization are different questions:

- *Who are you?* — the signature answered this correctly.
- *Are you allowed?* — nobody asked.

The router had a robust answer to the first question, which is exactly what
makes this hard to spot in review. There is no missing null check, no unchecked
input. The code looks complete because the check it does perform, it performs
well.

It was caught by a script that walked the whole authentication flow against a
running server, asserting on outcomes rather than on code paths: sign in as an
identity that is *not* invited, and confirm the API refuses. It returned `200`.

The fix is one call in the right place. The durable part is the regression test,
which is parametrised across both routers:

```python
@pytest.mark.parametrize("resolver", ["fixture", "live"])
async def test_both_routers_enforce_the_invite_gate(resolver):
    ...
```

Confirmed to work by reverting the fix and watching `[fixture]` fail while
`[live]` passed — which is precisely the divergence that caused the bug.

**If you have two code paths to the same resource, the test that matters is the
one parametrised over both.** Testing each individually is how they drift: each
suite passes, and the gap between them is what ships.

---

## What the three have in common

None of them threw. Each produced output a reviewer would accept:

- a plausible funding round, attributed to a real source
- a low score for an account, with a real number
- a `200` for a request with a valid token

Test suites do not catch this class on their own, because the code does what it
says; the problem is what it *doesn't* say. All three were found by adversarial
runs against a live system — reintroducing a defect to see whether the suite
notices, running the full scenario against real websites, walking an auth flow
and asserting on refusals rather than on successes.

The cheapest habit that finds them: **break your protection on purpose and
confirm the tests go red.** A suite that has never been seen to fail is an
assumption, not evidence.

---

The entity-safety gate is a standalone, dependency-free package
([`packages/entity-safety`](../../packages/entity-safety)), with the adversarial
cases published as a runnable benchmark
([`benchmark/`](../../packages/entity-safety/benchmark)). Everything above is
reproducible from a clone with no API keys: `npm install && npx gopilot -y`.
