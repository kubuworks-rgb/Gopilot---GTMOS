# confusable-entity-pairs

An open benchmark for one narrow question: **does your pipeline attach evidence
to the wrong company?**

Every case is a near-miss pair that shares a brand token with the target — which
is precisely why brand tokens must not drive attachment.

## What this is, and what it is not

Read this part before citing any number from it.

- **17 cases, version 0.1.0.** That is small. It is a starting point, not an
  authoritative standard, and a perfect score means "you handle these 17 cases",
  not "you are entity-safe".
- **Synthetic domains, real failure modes.** Cases use `acme.com`-style
  placeholders so the dataset carries no claims about real companies. The
  *shapes* are drawn from real confusions — the `optivian.ai` /
  `optivian.cloud` collision that motivated the suite is the first case.
- **Precision-oriented.** It measures whether you wrongly attach. A pipeline
  that refuses everything scores zero contaminations and is useless; that is why
  over-cautious rejections are reported separately rather than hidden.
- **Company entities only.** Parent, subsidiary, product, rebrand, sister brand,
  partner. Not people, places, or products-as-entities.
- **No leaderboard.** There is nothing to win here.

Contributions of new cases are genuinely wanted — see below.

## Running it

Against the reference implementation:

```bash
pip install -e packages/entity-safety
python packages/entity-safety/benchmark/run_benchmark.py --reference
```

Against **your** pipeline, whatever it is written in. Produce a JSON object
mapping case id to your decision, then:

```bash
python run_benchmark.py --predictions your_output.json
# or
your_pipeline | python run_benchmark.py --predictions -
```

Each case gives you everything needed to make a decision:

```json
{
  "id": "same-name-different-tld-the-historical-optivian-defect",
  "category": "same_name_different_tld",
  "target_entity": {
    "name": "Acme",
    "domain": "acme.com",
    "verified_official_domains": ["acme.com"],
    "known_relationships": [],
    "known_aliases": []
  },
  "candidate_source": {
    "url": "https://acme.ai/about",
    "role": "FIRST_PARTY",
    "claim_scope": "COMPANY_LEVEL"
  },
  "expected_decision": "UNATTACHED_ENTITY_AMBIGUOUS",
  "why": "different registrable domain, no proven relationship",
  "naive_matcher_would_conclude": "ATTACHED",
  "naive_matcher_is_wrong": true
}
```

Answer with one of three decisions:

| decision | meaning |
|---|---|
| `ATTACHED` | may support a claim about the target |
| `RELATED_ENTITY_ONLY` | known entity, but not the target |
| `UNATTACHED_ENTITY_AMBIGUOUS` | could not establish who this is about |

Only have attach/reject? Map both rejections to `UNATTACHED_ENTITY_AMBIGUOUS`
and pass `--collapse-rejections`. The report will say the distinction went
unscored, because losing the difference between "a different company" and "we
don't know" is itself a loss.

## Reading the score

```
  correct           17/17  (100.0%)
  contaminations    0   <- evidence attached that must not have been
  over-cautious     0   <- refused something it should have attached
  wrong reject kind 0   <- rejected, but misreported why
```

**Contaminations are the number that matters.** They are the failure that
silently corrupts a corpus: a fact about another company, attached, with no
error raised and nothing visibly wrong. Over-caution costs recall, which is
recoverable. Exit code is 1 if there is any contamination.

For calibration, a naive brand-token matcher — attach whenever the names match —
scores:

```
  correct           3/17  (17.6%)
  contaminations    14
```

It gets the three genuinely-attachable cases right and contaminates on
everything else. That is the baseline this dataset exists to beat.

## Contributing a case

Good cases are ones a reasonable implementation gets wrong.

**Wanted:**
- A confusion shape not yet covered — acquisitions that changed the corporate
  tree, joint ventures, franchises, regional licensees, holding companies with
  unrelated portfolios.
- Real collisions, anonymised to placeholder domains.
- Cases where the *correct* answer is `ATTACHED` but a conservative
  implementation refuses. The dataset currently has three; over-caution is
  under-represented and that is a real weakness.

**Not wanted:**
- Cases that only fail via a typo or malformed URL. That is input validation.
- Cases whose expected answer is contested. If two careful people disagree
  about the right decision, it does not belong until the ambiguity is resolved
  in the `why` field.
- Real company names in a way that asserts something about them.

**How:**

1. Add a case to `confusable_pairs.v<version>.json` with every field, including
   `why` — the reason is the review, and a case without a defensible one will be
   sent back.
2. Add the matching pair to `../tests/test_confusable_pairs.py` so the reference
   implementation is held to it too.
3. Run both:
   ```bash
   python -m pytest packages/entity-safety/tests -q
   python packages/entity-safety/benchmark/run_benchmark.py --reference
   ```
4. If your case makes the reference fail, say so in the PR. That is a finding,
   not a problem — a case the reference gets wrong is more valuable than one it
   already handles.

Bump the minor version when adding cases, so anyone quoting a score can say
which version it was against.
