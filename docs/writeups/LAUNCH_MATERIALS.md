# Launch materials (drafts for review)

Not posted anywhere. Drafts for the maintainer to review, edit and publish.

---

## a. Show HN

**Title** (80 char limit; the first is preferred):

> Show HN: A benchmark for evidence attaching to the wrong company

Alternatives:

> Show HN: Entity-safety – stop retrieval attaching facts to the wrong company
>
> Show HN: 17 adversarial cases for entity confusion in retrieval pipelines

**Body:**

```
Two companies, same brand token, different TLD:

  optivian.ai     the company you're researching
  optivian.cloud  a different company entirely

A press release on optivian.cloud announces a $40M Series B. A retrieval
pipeline scores it against the target: brand matches, industry matches,
headline is exactly what you were looking for. High similarity. Attach.

Your system now reports a funding round that never happened. Nothing
errored.

Similarity scoring can't fix this, because the two documents genuinely are
similar. Turning the threshold up loses real evidence; turning it down
admits more contamination. The axis is wrong.

I extracted the gate I built for this into a standalone package. It asks
two separate questions instead of one:

  1. Identity  - what's the relationship between source and target?
     (10 types: same entity, product of, subsidiary, parent, sister brand,
     rebrand, acquired by, partner, unrelated, unknown)
  2. Claim scope - what level is the claim actually about?

Keeping them separate is the point. A funding announcement about a PARENT
company is real, verified, correctly attributed - and still not a funding
claim about the subsidiary you're researching.

The adversarial cases are published as a benchmark you can run against your
own pipeline, in any language - emit {"case-id": "DECISION"} and score it.
For calibration, a naive brand-token matcher scores 17.6% with 14
contaminations.

It's 17 cases. That's small, and it's a starting point, not a standard. I'd
rather say that than have someone discover it. Contributions of new
confusion shapes are the main thing I want.

One thing I'd flag as method rather than result: I don't trust a suite that
has only ever passed. Removing the different-domain rejection fails 11 of
22 tests. My first attempt at breaking it - switching whole-token matching
to substring - broke nothing, which turned out to be a real gap in
coverage. Found by trying to break it, not by reading it.

The package has no dependencies. The wider project it came from is an
evidence-backed account research tool; it runs from a clone with no API
keys (npm install && npx gopilot -y). There's also a write-up of three
bugs from it that all produced confident, wrong answers rather than
crashing - wrong-entity contamination, unknown silently becoming a
confident zero, and authentication being mistaken for authorization.

https://github.com/kubuworks-rgb/Gopilot---GTMOS
```

**Notes for posting**

- HN punishes hype; there are no adjectives above by design.
- The honest "17 cases, that's small" line is load-bearing. A benchmark that
  overstates coverage gets dismissed; one that's early and says so gets
  contributions.
- Expect the first comments to be "how is this different from NER / entity
  linking?" A good answer: it isn't entity *linking* — it assumes you already
  know who you're asking about, and decides whether a given passage may attach.
  It's the gate after retrieval, not the resolver before it.
- Second likely question: "why not use an LLM?" Answer: the decision needs to be
  auditable and identical on every run, and a rejection a user can't inspect is
  indistinguishable from a bug.
- Post on a weekday morning US time. Reply to everything for the first two hours.

---

## b. Technical write-up

Full draft at [`three-bugs.md`](three-bugs.md) — publish as-is or syndicate.

Covers the three bugs with real before/after numbers, each framed as a failure
mode the reader probably has:

1. **Wrong-entity contamination** — the Optivian defect, why similarity can't
   fix it, and the deliberate-break result (11 of 22 red).
2. **Unknown becoming a confident zero** — `fly.io` 30 → 66, and the general
   shape: a sentinel indistinguishable from a real measurement.
3. **Authentication mistaken for authorization** — one router gated, one not,
   and the parametrised test that locks it.

Closing point is the transferable one: all three produced output a reviewer
would accept, and the cheapest habit that finds them is breaking your protection
on purpose to confirm the tests go red.

---

## c. Resume / portfolio blurb

**GoPilot — evidence-backed account research** ·
[github.com/kubuworks-rgb/Gopilot---GTMOS](https://github.com/kubuworks-rgb/Gopilot---GTMOS)

- Found and fixed an authorization bypass where one of two API routers
  authenticated requests but never checked whether the identity was permitted;
  locked it with a test parametrised across both routers, verified by reverting
  the fix and confirming only the affected router failed.
- Built an entity-attachment gate (10 relationship types × 6 claim scopes) that
  prevents evidence cross-attaching between similarly-named companies;
  published the 17 adversarial cases as a runnable benchmark, and demonstrated
  the suite catches regressions by removing the protection and observing 11 of
  22 tests fail.
- Fixed a scoring defect where a fully-unknown dimension scored as a confident
  zero and was multiplied into the final rank, costing one account more than
  half its priority (30 → 66); re-verified against a rebuilt live stack, not
  only in unit tests.
- 528 tests; CI green on Linux, macOS and Windows; one-command setup from a
  clean clone in 34s with no API keys, verified on fresh CI runners rather than
  a developer machine.
