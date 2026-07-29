"""org-scope products sku and inventory_events event_id uniqueness

Revision ID: ffdda217be31
Revises: 48acda15ea39
Create Date: 2026-07-28 23:36:06.753192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffdda217be31'
down_revision: Union[str, Sequence[str], None] = '48acda15ea39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # products.sku was a plain unique index (see d6e00aa295e6) — drop it,
    # replace with UNIQUE(organization_id, sku). No plain single-column
    # index on sku survives this: get_product_by_sku() still queries by
    # sku alone (unscoped) until product_service.py is org-threaded in a
    # later Epoch 10 PR (#143), so this is a deliberate transitional
    # widening, not a finished state — see that PR for the corresponding
    # service-layer fix. Safe in the meantime because product_service.py
    # has no way to create a product outside org 1 yet (organization_id
    # isn't a parameter there until #143), so no real duplicate-sku
    # collision across orgs can occur through the app today, only via
    # direct DB manipulation (e.g. this PR's own verification).
    op.drop_index("ix_products_sku", table_name="products")
    op.create_unique_constraint("uq_products_org_sku", "products", ["organization_id", "sku"])

    # inventory_events.event_id was a named UniqueConstraint (see
    # 91fbfd575d93) — drop it, replace with UNIQUE(organization_id,
    # event_id). The 3 call sites this affects (idempotency pre-check,
    # duplicate-catch retry, recipe-cascade derived id) are updated in
    # this same PR, in app/services/inventory_service.py — unlike sku,
    # this one lands with its service fix in the same PR, per issue #142.
    op.drop_constraint("uq_inventory_events_event_id", "inventory_events", type_="unique")
    op.create_unique_constraint(
        "uq_inventory_events_org_event_id", "inventory_events", ["organization_id", "event_id"]
    )


def downgrade() -> None:
    """
    Downgrade schema.

    Only safe if no two orgs currently share a sku or event_id — this
    narrows both constraints back to a single global column, which fails
    outright (a real Postgres unique-violation error, not a silent
    partial downgrade) if any real cross-org duplicate exists by the time
    this runs. Expected: this migration is only realistically downgraded
    shortly after deploy, before any second org has created real
    duplicate data.
    """
    op.drop_constraint(
        "uq_inventory_events_org_event_id", "inventory_events", type_="unique"
    )
    op.create_unique_constraint(
        "uq_inventory_events_event_id", "inventory_events", ["event_id"]
    )

    op.drop_constraint("uq_products_org_sku", "products", type_="unique")
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)
