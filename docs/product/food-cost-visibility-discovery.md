# Food Cost Visibility — Discovery Findings (2026-09-04)

## Why this exists

IMS has no real users yet — there's no one to actually interview about what
they need from the app. Rather than guess, this discovery was run as a
structured two-persona simulation: a restaurant-owner persona ("Maria",
grounded in the app's actual target use case — see `ROADMAP.md`'s "Path A"
section) and a product-analyst persona ("Priya"), each run as an
independent agent, genuinely relaying messages back and forth rather than
one agent writing both sides. Neither persona was told what feature to
recommend going in.

This is a synthetic proxy for real user research, not a replacement for it
— treat every finding below as a hypothesis to validate against a real
restaurant owner the moment one exists, not as settled fact. Its value is
narrowing the solution space and avoiding obviously wrong bets (see "Not
worth building" below) before spending real engineering time.

**Trigger:** Sinan observed that as a packaged desktop app, IMS gives a
non-technical user no obvious way to get their own data in — there's no
manual entry screen anywhere in the dashboard except Purchase Orders
(confirmed via a real codebase check: `grep` across `dashboard/views/*.py`
for a mutating form found only `recipes.py` and `purchase_orders.py`).

## Persona grounding

**Maria Alvarez** — owner-operator, "Casa Alvarez," independent 60-seat
restaurant, 6 years open, no dedicated back-office staff (splits admin
work with her kitchen manager, Tomas). Non-technical but comfortable with
a smartphone and basic POS use. Skeptical of new software from past
experience with a scheduling app that didn't stick.

Her actual tools: Toast POS at the register (tracks dish-level sales,
not ingredient depletion), two suppliers delivering on paper invoices, no
formal waste tracking at all, a rough monthly physical count with a paper
tally sheet.

## Key reframe (read this first)

Maria didn't want more data-entry screens. Her own words, closing the
interview:

> "I was hoping for LESS work and a number I actually trust... I assumed
> I'd log in to this thing and it'd just show me [food cost percentage],
> updating itself. Instead I logged in and saw a blank dashboard with no
> obvious 'add' button anywhere, and honestly I felt a little dumb...
> that's kind of the opposite of what I wanted."

The number she wants — **food cost percentage** (COGS ÷ revenue),
currently something she only sees once a quarter from her accountant,
"ancient history" by the time she can act on it — is the actual product
outcome. Every data-entry mechanism below is plumbing toward that number,
not the deliverable itself. This should drive UI sequencing: showing
*some* visible, improving number early matters more than perfecting any
one entry form.

## Findings, ranked

### Must have

**1. A "log waste" quick-entry, ~10 seconds, tap/pick-list/rough-quantity
only — never free text.**

Waste is currently tracked nowhere — "in nobody's memory reliably, zero
paper trail" — at an estimated 8-15 small toss-outs per shift ("death by
a thousand cuts... each one feels too small to matter"). A clipboard-based
alternative was proposed and explicitly rejected as unrealistic mid-rush:

> "Nobody's gonna walk over to a clipboard, find a pen that works... by
> day four the pen's missing."

Must work on a personal phone (no dedicated kitchen tablet/kiosk — "someone
would drop it in the fryer within a month"), and must not require typed
login per entry: a full username/password every time is a stated
dealbreaker ("he'll just throw the tomato away and say nothing"). A PIN
or a session that simply stays logged in is the bar.

**2. A guided, credential-based POS connector (Toast, for this persona) —
not a raw API key, not a manual CSV import as the ongoing mechanism.**

She can technically export a Toast sales CSV (confirmed: ~2-5 minutes
once she knows the screen) but was explicit that she won't do this on any
sustainable cadence: "every day? that's not gonna happen... that's
exactly the kind of thing that dies after four days." The only version of
POS integration that survives contact with her real life is a
bank-app-style login flow ("Connect to Toast," normal username/password,
not "find your API credentials"), ideally with a live onboarding call for
the one-time setup. Batch sync (daily or weekly) is sufficient — she
explicitly does not need real-time.

**3. Price-creep flagging at Purchase Order entry (unprompted finding).**

> "If there's ever a way for the system to flag 'hey, this item cost more
> than last time'... that'd actually save me real money, not just time.
> Right now I only catch price creep by accident, months later."

Cheap relative to its payoff — reuses the one dashboard screen that
already exists (Purchase Orders) and a field that's already tracked
(`PurchaseOrderLine.unit_cost`).

**4. A visible, always-updating food-cost % (or at minimum COGS-vs-revenue)
tile on the dashboard, fed by whatever data streams exist so far.**

The actual deliverable, per the reframe above — not a downstream nice-to-have
gated on every entry screen being perfect.

### Nice to have later

- Manual single-event logging for adjustment/damage/return, reusing the
  waste quick-entry pattern — inferred, not requested; she never described
  needing this day-to-day.
- Photo/OCR capture of paper delivery invoices — she named illegible
  handwriting as a real headache, but didn't ask for OCR by name. Worth
  validating before building; it would also feed price-creep detection
  automatically.
- A structured cycle-count/reconciliation screen — she already has a
  working (if crude) monthly gut-check; more valuable once real waste +
  sales data exist to reconcile against, not before.

### Not worth building (yet)

- **Real-time POS sync** — she was explicit that even a nightly export is
  a stretch; a batch pull (daily/weekly) matches her actual usage pattern.
- **Dedicated kitchen hardware** — rejected unprompted ("dropped in the
  fryer within a month"). Bring-your-own-phone only.
- **Any free-text entry** — every workable pattern she described was
  tap/pick-list/rough-number. Nothing requiring a composed sentence
  survives a rush shift.
- **Returns/credit tracking** — her own words: "that one's small, don't
  build for that first."

## Real technical constraints found while scoping (not from the interview)

- **No revenue data exists in IMS today.** `Product` has no
  `selling_price` field, and IMS-native `SALE` events only carry
  quantity, never a dollar amount. A real food-cost % needs a revenue
  source — either the Toast connector (which does carry per-item sale
  price) or a new manual price field as a fallback for POS-less
  deployments. This means **item 4 (food-cost tile) cannot ship before
  item 2 (POS connector) for any org without one**, unless a manual
  price fallback is scoped in too.
- **The generic ingestion core already exists and is reusable as-is.**
  `app/services/ingestion_service.py::ingest_events()` takes generic
  `{sku, event_type, quantity, event_id}` rows and is already used by
  both the CSV importer and the webhook receiver. A Toast connector's
  backend is mostly: pull Toast's sales report → translate each line into
  that same shape → call the existing function. The new work is the
  OAuth/credential flow, a periodic sync job, and a one-time UI to map
  Toast menu items to IMS products (Toast doesn't know IMS SKUs).
- **No scheduler/cron infra exists in this codebase** — confirmed via
  `ROADMAP.md`'s Epoch 9 section, which reached the same conclusion for
  automated retraining: the proportionate answer is a plain host cron
  entry (see `scripts/retrain_cron.sh` for the exact precedent), not new
  in-app scheduling infrastructure.
- **The dashboard mutating-action pattern is already established and
  reusable.** `dashboard/po_actions.py` (mutating service calls,
  `SessionLocal()`, in-process — same pattern as `admin_actions.py`/
  `recipe_actions.py`) + `dashboard/views/purchase_orders.py` (the
  `st.Page` registered in `dashboard/app.py`'s `st.navigation()`) is the
  template a new "Log Waste" page should follow exactly.
- **The mobile "stay logged in" requirement is largely already solved.**
  The dashboard's login is a server-side Streamlit session (see
  `dashboard/auth.py`), not a client-held token — confirmed elsewhere this
  session that a disconnected session has no time-based expiry until the
  server process itself restarts. As long as the mobile app doesn't get
  force-killed between waste-logging moments, "stays logged in" is
  already the existing behavior, not new work.

See `ROADMAP.md`'s "Food Cost Visibility" section for the resulting scope
and build sequence.
