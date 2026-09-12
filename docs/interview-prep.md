# Interview Prep / Architecture Study Guide

A living quiz bank for "prepare me for an interview" or "ask me about
the codebase" sessions. This is **not** a set of answers to memorize —
it's pointers to the real code plus a checklist of what a complete
answer needs to touch. The exercise is: read the file, explain it in
your own words out loud or in writing, then use the checklist to see
what you missed.

## How to use this with Claude

Say "quiz me" / "prepare me for an interview" and point at a topic
below (or let Claude pick). The expected flow:

1. Claude asks the question, you answer from memory — no re-reading the
   source first.
2. Claude checks your answer against that topic's checklist and tells
   you what's missing or wrong, pointing at the specific file/line if
   you need to go verify it.
3. Update the **Study Log** at the bottom: date, topic, what was solid,
   what had gaps. Gaps are what to actually re-study, not the topic as
   a whole.

Claude should resist just reciting the checklist as "the answer" —
the point is you reconstructing it, not being told it again.

---

## Topic 1: Event sourcing + idempotency (`inventory_service.py`)

**File:** `app/services/inventory_service.py`

**Ask:** "Walk me through what happens, step by step, when a POS sells
a dish that has a recipe — from `record_event()` down to what's
actually committed to the database. What guarantees does this give
you, and where would it break if you removed one piece?"

Checklist a complete answer should hit:
- [ ] `record_event()` is the transaction boundary — one `db.commit()`
  at the end, not one per event. `_apply_event()` and
  `_cascade_recipe_consumption()` only `db.flush()`, never commit.
- [ ] Idempotency: `event_id` is client-supplied, unique per
  `(organization_id, event_id)`. A duplicate is detected by lookup in
  `_apply_event()` **and** backstopped by a DB unique constraint caught
  as `IntegrityError` in `record_event()` — two layers because a
  race between the lookup and the insert is real, not hypothetical.
- [ ] `with_for_update()` on the `InventoryState` row (line ~112) locks
  it for the duration of the transaction — this is what makes
  concurrent sales of the same product serialize instead of both
  reading stale `quantity` and overselling.
- [ ] The oversell guard (`new_quantity < 0` check) only applies to
  `SALE`/`DAMAGE`/`WASTE`, not `ADJUSTMENT` — can you explain why an
  adjustment is allowed to go negative?
- [ ] Recipe cascade: selling 1 dish generates **synthetic SALE events**
  for each ingredient (not a new event type) — why does that matter for
  `forecast_service.py`/`restock_service.py` (they just sum SALE
  outflow, no special-casing needed)? What does "one level deep only"
  mean and what does it *not* handle (a dish made of dishes)?
- [ ] Component event IDs are derived (`f"{source_event_id}:component:{item.component_product_id}"`)
  — why does this make the cascade itself idempotent too, not just the
  triggering event?
- [ ] Failure handling: `IntegrityError` → rollback, re-check for the
  now-existing duplicate, return it (this is what makes a client's
  retry-after-timeout safe). Any *other* exception (e.g. an ingredient
  runs out mid-cascade) → rollback, re-raise, **no partial state
  survives**. What's the actual comment in the code about *why* the
  bare `except Exception: db.rollback()` exists (hint: it references a
  real failing test, not a theoretical concern)?

**Breaking exercise (from the reviewer's suggestion #2):** comment out
`with_for_update()` or the final `db.rollback()` in the generic
exception handler, then write a small concurrent test (two threads/
sessions selling the last unit of the same product) or a test that
forces the cascade to fail partway. What actually breaks? Does it
break the way you predicted before running it?

---

## Topic 2: Webhook auth — per-org secret (`app/core/auth.py`, `app/api/webhooks.py`)

**Ask:** "Why does each organization have its own `webhook_secret`
instead of one shared secret for the whole deployment? Walk me through
`require_webhook_signature()` line by line."

Checklist:
- [ ] The actual vulnerability a shared secret would have: any one
  org's leaked/brute-forced credential could post fake inventory events
  into **any other org's** ingestion endpoint, not just its own.
- [ ] `organization_id` comes from the **route path**
  (`POST /webhooks/{organization_id}/ingest`), not a header or body
  field — the org is public knowledge, only the signature is secret.
- [ ] HMAC-SHA256 over the **raw body bytes**, keyed by that org's
  `organizations.webhook_secret` — and the specific reason
  `request.body()` has to be read *before* the route handler parses
  JSON (Starlette caches the body, so this doesn't break the route's
  own Pydantic parsing).
- [ ] `hmac.compare_digest()` instead of `==` — what attack does a
  naive string comparison enable here, specifically?
- [ ] `webhook_secret IS NULL` disables verification for *that org
  only* — same "unset = disabled" shape as the old single env var, now
  per-org. What's the trade-off of a loud `logger.warning` on every
  such request instead of a boot-time scan?

---

## Topic 3: Multi-tenancy — three enforcement layers

**Canonical reference:** `docs/multi-tenancy.md` (read this in full —
it's the most detailed doc in the repo and already answers most of
this from a design-history angle; the exercise is being able to say it
without having it open).

**Ask:** "Explain why `organization_id` gets checked in the DB layer,
the application layer, and the analytics layer, when in several places
a comment says it's 'defense in depth, not closing a live gap.' Give a
concrete example of each layer, and explain what that specific phrase
means using the actual code."

Checklist:
- [ ] **DB layer (structural):** composite FKs — `UNIQUE (organization_id, id)`
  on parent tables lets children declare
  `FOREIGN KEY (organization_id, product_id) REFERENCES products (organization_id, id)`.
  Why does this make a cross-org reference impossible to *write*, not
  just wrong-if-you-forget-a-filter?
- [ ] **Application layer (explicit, not implicit):** every service
  function takes `organization_id` as an explicit parameter; resolved
  per-request via `get_current_org_id()`, never from a JWT claim or
  contextvar. Why does re-reading the live `User` row every request
  (instead of trusting the JWT) matter for a user who gets moved to a
  different org mid-session?
- [ ] **Analytics layer:** the dbt join
  `ON e.product_id = p.product_id AND e.organization_id = p.organization_id`
  — explain concretely why the *second* clause is provably redundant
  here (because `product_id` is already globally unique) and why it's
  kept anyway. This is the exact "defense in depth, not closing a live
  gap" case — can you say what would have to be true elsewhere in the
  system for that redundant clause to actually start mattering?
- [ ] Can you name the one real, non-redundant IDOR bug this arc found
  (hint: `replay_service.py` — what did an unfiltered `DELETE` do to
  other orgs' data), versus the three lookups that grep found and
  turned out to be already-safe-by-construction?
- [ ] What's deliberately **not** org-scoped, and why is each one
  correct rather than an oversight (`authenticate_user`'s email lookup,
  `POST /api/inventory/export`, `retrain_cron.sh` only covering org 1)?

---

## Topic 4: Account lockout (`app/services/auth_service.py`)

**Ask:** "Why was this added, and what specific gap did it close that
the multi-tenancy/webhook work didn't already cover?"

Checklist:
- [ ] The gap: mobile clients reach the dashboard over Tailscale, which
  meant `SECURITY.md`'s "port is never publicly exposed" assumption no
  longer covered every real access path — login had zero brute-force
  protection on that path.
- [ ] Where the counter lives (`User.failed_login_attempts`,
  `locked_until`) — why per-account state in the DB instead of an
  in-memory/IP-based rate limit (what does IP-based miss on a shared
  Tailscale exit, and what does account-based catch instead)?
- [ ] What resets the counter, and what happens to a *stale* lockout
  (an expired `locked_until` isn't proactively cleared — where/when
  does it actually get cleared)?

---

## Topic 5: CI/security pipeline additions

**Ask:** "What does the Semgrep job actually check, and why was
`docker-build` folded into `scan` instead of left separate?"

Checklist:
- [ ] Semgrep OWASP Top 10 ruleset — what class of bug is it looking
  for that unit tests wouldn't catch?
- [ ] The docker-build/scan dedup — what was being built twice before,
  and what was the actual deviation from the issue's own proposed
  options (worth being able to say *why* you diverged, not just that
  you did)?

---

## Study Log

_Most recent first. One entry per quiz session — a couple lines, not a
transcript._

<!-- Add entries like:
### 2026-08-28 — Topic 1 (event sourcing)
Solid on: transaction boundary, idempotency double-check.
Gap: couldn't explain why cascade event IDs need to be derived from
source_event_id for the cascade itself to be idempotent — re-study.
-->
