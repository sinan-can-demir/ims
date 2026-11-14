import re

# event_id is the idempotency key, and InventoryEvent is UNIQUE(organization_id,
# event_id). The system derives some ids itself:
#   - PO receive:    "po-{purchase_order_id}-line-{line_id}"
#   - recipe cascade: "{source_event_id}:component:{component_product_id}"
# If a client could submit one of those first, the later system-generated
# event would hit the idempotency check and silently no-op (a PO line never
# received, a recipe component never deducted). Client-supplied ids (single
# event, CSV import, webhook) are therefore validated against this shape.
_PO_LINE_RE = re.compile(r"^po-\d+-line-\d+$")
_COMPONENT_MARKER = ":component:"


def reject_reserved_event_id(event_id: str) -> str:
    if _PO_LINE_RE.match(event_id) or _COMPONENT_MARKER in event_id:
        raise ValueError(
            "event_id uses a reserved format "
            "('po-<id>-line-<id>' or containing ':component:') "
            "that the system generates itself"
        )
    return event_id
