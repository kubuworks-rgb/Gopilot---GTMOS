# OSS monetization — scope

**Status: scoping only. Nothing here is built, and nothing here is scheduled.**

This document exists so that if GoPilot is ever monetized, the shape is decided
now — while there is no revenue pressure — rather than later, under it. A
constraint written down before it costs anything is worth more than one written
down after.

No billing code, no Stripe, no plan tiers, and no dependencies were added in
producing this.

---

## 1. What stays free forever

**Hard constraint. The future design must respect this or be rejected.**

The BYOA core loop is free, unmetered, and ungated, whether self-hosted or run
by someone else:

```
import accounts → verify identity → research against official sources →
extract and attach evidence → deterministic scoring → opportunity brief →
human review → export
```

Free means specifically:

- **No feature gating.** Not a reduced free tier. The same loop, complete.
- **No usage caps.** No account limits, research-run limits, or export limits
  used as a pricing lever. (The private-alpha limits that exist in config are
  operational safety valves for a deployment, not a pricing mechanism, and must
  never become one.)
- **No paid dependency underneath.** No search provider, no enrichment provider,
  no LLM. This is what makes the claim honest rather than technical.
- **No degradation over time.** Moving something already in the core behind
  payment later is the specific failure this section exists to prevent.

### Why this is load-bearing, not generosity

Every claim GoPilot makes publicly rests on it. The README states the core has
no metered dependency; the write-ups invite people to fork it; the extension
guide tells people where to put their hands. If the core is later gated, all of
that becomes retroactively misleading, and the people who invested effort on the
strength of it are the ones penalised.

The reputational cost of that is larger than any revenue it would produce. This
is the trust foundation. **Treat it as immutable.**

---

## 2. What could honestly carry a price

Only things that cost someone real money to provide, or that are genuinely
optional to the core.

### 2a. Hosted convenience — flat fee, no markup

"We run it for you." Skip self-hosting: no Postgres, no Redis, no reverse
proxy, no certificate renewal, no upgrades.

- **Charge:** flat monthly fee.
- **No markup, because there is nothing metered to mark up.** The core has no
  third-party cost. The fee covers hosting and operations, which is exactly what
  it says.
- **Free path unchanged:** self-hosting stays fully supported and fully
  documented. The deployment runbook does not get worse to make hosting more
  attractive.

This is the honest case, and the easiest to defend: the buyer is paying for
someone else's time and infrastructure, not for access to their own software.

### 2b. Managed discovery adapter — markup, *if it is ever built*

Autonomous discovery is currently experimental and off by default. If it is ever
developed to the point of needing paid search providers (Exa, Tavily), a hosted
version could manage the provider relationship and keys.

- **Charge:** a markup on metered third-party usage the hosted service pays for
  on the user's behalf.
- **Why that is honest:** the hosted service carries the provider contract, the
  key custody, the rate limits, and the bill. A markup on a cost genuinely
  incurred is a service fee, not rent.
- **Free path unchanged:** self-hosters bring their own provider key and pay the
  provider directly at cost — exactly as today. Nothing about BYOK gets worse.
- **Conditional on two things that are not true yet:** discovery being built out
  at all, and it actually requiring paid providers.

### 2c. Premium enrichment provider — markup, *if it is ever added*

Some things cannot be established by reading a company's own website:
verified headcount, funding history, contact data. Today GoPilot answers
`UNKNOWN` for these and says so, which is the correct behaviour and must remain
the default.

If a paid enrichment provider is ever integrated, the same pattern applies:
optional, hosted-managed, marked up on real metered cost; self-hosted BYOK
available at provider cost.

**The constraint that matters here:** enrichment must never become the way the
core answers a question it currently answers honestly. "Unknown, and here is
why" is a feature. Replacing it with "upgrade to find out" would gate the core
by the back door.

---

## 3. Explicitly not in scope

Deliberately deferred, not forgotten:

- Stripe or any payment integration
- Plan tiers, seat-based pricing, per-user licensing
- Usage caps on the free core, of any kind
- Anything that gates the research loop behind payment
- Trials, feature flags tied to billing state, or upgrade prompts in the product

An earlier phase of this project scoped billing in detail and then removed it,
because building payment infrastructure ahead of demand is how a free tool
quietly becomes a funnel. That lesson stands. **Do not re-scaffold this
speculatively.**

---

## 4. Precedent, and the critique worth learning from

The model above is adapted from OpenSEO, an open-source project that monetizes
via a genuinely free self-hostable core with BYOK, an optional hosted tier at a
low flat fee, a percentage markup on third-party data usage the hosted version
manages, MCP-native distribution to coding agents, and explicit
fork-friendliness — which produced at least one real third-party product built
on top of it.

Two things are worth taking from it directly:

1. **Markup on managed third-party usage is defensible** when the hosted service
   really does carry the cost, and self-hosters really can bring their own key.
2. **MCP-native distribution reaches a different audience** than product
   marketing does — agent builders rather than end buyers.

**The critique it drew is the more useful part.** Being "free" while requiring a
paid third-party key underneath reads as misleading to some users: the software
is free, but doing anything with it is not.

GoPilot avoids that specific criticism structurally rather than rhetorically.
The core has no metered dependency at all — no search provider, no enrichment
provider, and no LLM — because reading a company's own website *is* the
mechanism. There is nothing in the core to mark up even if someone wanted to.

That is the asymmetry to protect. The markup mechanism can only ever attach to a
clearly-optional add-on, and if the core is ever given a paid dependency, this
entire position collapses. **A paid dependency in the core is a design
regression, not a business decision.**

---

## 5. When to revisit

This is not built because there is no demand for it. Signals that would justify
reopening it, roughly in order of strength:

| Signal | What it would justify |
|---|---|
| Repeated unprompted requests to host it — people who tried self-hosting and would rather pay than operate it | §2a, hosted convenience |
| Discovery being genuinely built out *and* requiring paid providers | §2b, managed adapter |
| Users repeatedly blocked by an `UNKNOWN` that only paid data can resolve | §2c, enrichment — and only if the honest-unknown default survives |
| Someone forking it commercially and asking for a support relationship | A support arrangement, which needs none of the above |

**None of these is currently true.** Not one line of billing code should exist
until at least one is, and the first question at that point should still be
whether it is worth the complexity.

A useful test before building any of it: *would this still be worth doing if it
produced no revenue at all?* For hosting, plausibly yes — it is a real
convenience. For anything that touches the core loop, the answer is no, which is
the answer.
