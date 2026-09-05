# PO dashboard forms never collect `unit_cost` — every line created via the UI has it `None`

## Summary

`PurchaseOrderLine.unit_cost` is a real, tracked field — the API schema
accepts it, the dashboard displays a "Unit cost" column for it — but
neither dashboard form that creates a line (`purchase_orders.py`'s
"Create draft" manual form, or its "Add line" form on an existing draft)
has an input for it. Every purchase order ever created through the
dashboard has `unit_cost = None` on every line, shown as `-` in the line
table. Only a caller hitting the raw API directly with `unit_cost` in the
request body has ever actually set it.

## Why happened?

`dashboard/po_actions.py`'s `create_po()` and `add_line()` wrapper
functions don't accept a `unit_cost` parameter at all — they build
`PurchaseOrderLineCreate(product_id=..., quantity=...)` with `unit_cost`
left at its schema default of `None`. The corresponding
`dashboard/views/purchase_orders.py` forms (`create_po_form` and each
draft's `add_line_form_{po_id}`) only render a product selector and a
quantity `number_input` — no `unit_cost` input was ever added alongside
them. Nothing enforces the two staying in sync; the display column
(`purchase_orders.py:189`) was added independently and just renders
whatever's there, which is always nothing from this path.

Found while implementing the "Food Cost Visibility" Phase 2 price-creep
flag (`ROADMAP.md`) — that feature compares a new line's `unit_cost`
against the most recent prior line for the same product, which is
meaningless if no dashboard-created line has ever had a cost to compare.

## Rule

A schema/model field that's optional and has a display column doesn't
mean it's actually reachable from the UI — check the *form*, not just the
column, before assuming a piece of data can exist in practice.

## Fix

Added a `unit_cost` number input (optional, `min_value=0.0`) to both
`create_po_form` and each draft's `add_line_form_{po_id}`, threaded
through `create_po()`/`add_line()` into the existing
`PurchaseOrderLineCreate(unit_cost=...)` construction — no service-layer
or schema change needed, since both already accepted it. Shipped together
with the price-creep flag itself (same PR) since the flag has no real
data to compare against otherwise.
