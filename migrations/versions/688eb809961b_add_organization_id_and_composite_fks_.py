"""add organization_id and composite fks to inventory_events inventory_state recipe_items purchase_orders

Revision ID: 688eb809961b
Revises: 49570bffe51e
Create Date: 2026-07-28 21:35:38.423354

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "688eb809961b"
down_revision: Union[str, Sequence[str], None] = "49570bffe51e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Unlike PR 2 (49570bffe51e), these four tables backfill *existing* rows
    # via their already-org-tagged parent from that PR (products/suppliers),
    # not a hardcoded '1' literal — add nullable, UPDATE...FROM the parent,
    # then tighten to NOT NULL. Same 3-step idiom as event_id's backfill
    # (91fbfd575d93), generalized to a join instead of a per-row computed
    # constant. On today's single-tenant data this produces the same
    # values a literal default would (every parent is org 1), but it's the
    # correct general-case backfill, not a shortcut that happens to work
    # now.
    #
    # server_default='1' is still set on every column below (in the same
    # alter_column call that tightens NOT NULL) for the *same* reason PR 2
    # kept it permanently: inventory_service.py/recipe_service.py/
    # purchase_order_service.py don't thread organization_id through
    # explicitly until later Epoch 10 PRs, so every write path that
    # creates a row in these four tables between now and then still needs
    # a DB-level default to satisfy the NOT NULL constraint — the
    # join-based backfill above only back-fills rows that already exist
    # at migration time, it has no bearing on future inserts.

    # --- inventory_events (via products, product_id NOT NULL) ---
    op.add_column("inventory_events", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE inventory_events
        SET organization_id = products.organization_id
        FROM products
        WHERE inventory_events.product_id = products.id
        """
    )
    op.alter_column("inventory_events", "organization_id", nullable=False, server_default="1")
    op.create_index(
        op.f("ix_inventory_events_organization_id"), "inventory_events", ["organization_id"]
    )
    op.create_foreign_key(
        "fk_inventory_events_organization_id_organizations",
        "inventory_events",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_inventory_events_org_product",
        "inventory_events",
        "products",
        ["organization_id", "product_id"],
        ["organization_id", "id"],
    )
    # created_by_id is nullable (webhook events have no human actor) — this
    # composite FK must use Postgres's default MATCH SIMPLE, NOT MATCH
    # FULL. MATCH FULL requires every column in the FK to be NULL
    # together or none at all; MATCH SIMPLE (the default when `match` is
    # left unspecified) only enforces the FK when ALL referencing columns
    # are non-NULL. Since organization_id here is NOT NULL but
    # created_by_id can be NULL, MATCH FULL would reject every
    # NULL-created_by_id row outright (a single NULL column in a MATCH
    # FULL pair fails the "all NULL or none NULL" rule). Leaving `match`
    # unset is what makes NULL created_by_id rows pass through unchecked,
    # while any non-NULL created_by_id is still fully validated against
    # (organization_id, id) on users.
    op.create_foreign_key(
        "fk_inventory_events_org_created_by",
        "inventory_events",
        "users",
        ["organization_id", "created_by_id"],
        ["organization_id", "id"],
    )

    # --- inventory_state (via products; PK stays product_id, globally unique) ---
    op.add_column("inventory_state", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE inventory_state
        SET organization_id = products.organization_id
        FROM products
        WHERE inventory_state.product_id = products.id
        """
    )
    op.alter_column("inventory_state", "organization_id", nullable=False, server_default="1")
    op.create_index(
        op.f("ix_inventory_state_organization_id"), "inventory_state", ["organization_id"]
    )
    op.create_foreign_key(
        "fk_inventory_state_organization_id_organizations",
        "inventory_state",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_inventory_state_org_product",
        "inventory_state",
        "products",
        ["organization_id", "product_id"],
        ["organization_id", "id"],
    )

    # --- recipe_items (via products; two independent NOT NULL FKs) ---
    op.add_column("recipe_items", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE recipe_items
        SET organization_id = products.organization_id
        FROM products
        WHERE recipe_items.finished_product_id = products.id
        """
    )
    op.alter_column("recipe_items", "organization_id", nullable=False, server_default="1")
    op.create_index(op.f("ix_recipe_items_organization_id"), "recipe_items", ["organization_id"])
    op.create_foreign_key(
        "fk_recipe_items_organization_id_organizations",
        "recipe_items",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    # Two independent composite FKs, one per product reference. Each one
    # alone already forces its column to belong to the same org as the
    # recipe_item row — so finished_product_id's FK plus
    # component_product_id's FK together are sufficient to guarantee a
    # recipe never links two products from different orgs. No extra CHECK
    # constraint is needed on top of these two FKs for that guarantee.
    op.create_foreign_key(
        "fk_recipe_items_org_finished_product",
        "recipe_items",
        "products",
        ["organization_id", "finished_product_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_recipe_items_org_component_product",
        "recipe_items",
        "products",
        ["organization_id", "component_product_id"],
        ["organization_id", "id"],
    )

    # --- purchase_orders (via suppliers) ---
    op.add_column("purchase_orders", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE purchase_orders
        SET organization_id = suppliers.organization_id
        FROM suppliers
        WHERE purchase_orders.supplier_id = suppliers.id
        """
    )
    op.alter_column("purchase_orders", "organization_id", nullable=False, server_default="1")
    op.create_index(
        op.f("ix_purchase_orders_organization_id"), "purchase_orders", ["organization_id"]
    )
    # UNIQUE(organization_id, id) — purchase_orders becomes a composite-FK
    # *parent* in the next PR (purchase_order_lines composite-FKs to it),
    # same reason products/suppliers/users got this in PR 2.
    op.create_unique_constraint(
        "uq_purchase_orders_org_id", "purchase_orders", ["organization_id", "id"]
    )
    op.create_foreign_key(
        "fk_purchase_orders_organization_id_organizations",
        "purchase_orders",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_purchase_orders_org_supplier",
        "purchase_orders",
        "suppliers",
        ["organization_id", "supplier_id"],
        ["organization_id", "id"],
    )
    # created_by_id is NOT NULL for purchase_orders (unlike
    # inventory_events.created_by_id) — POs are only ever created via an
    # authenticated API call, see app/models/purchase_order.py. MATCH
    # SIMPLE vs MATCH FULL is therefore moot here (no NULL column value
    # ever reaches this FK), but left as the same unspecified/default
    # MATCH SIMPLE as every other composite FK in this migration for
    # consistency.
    op.create_foreign_key(
        "fk_purchase_orders_org_created_by",
        "purchase_orders",
        "users",
        ["organization_id", "created_by_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_purchase_orders_org_created_by", "purchase_orders", type_="foreignkey")
    op.drop_constraint("fk_purchase_orders_org_supplier", "purchase_orders", type_="foreignkey")
    op.drop_constraint(
        "fk_purchase_orders_organization_id_organizations", "purchase_orders", type_="foreignkey"
    )
    op.drop_constraint("uq_purchase_orders_org_id", "purchase_orders", type_="unique")
    op.drop_index(op.f("ix_purchase_orders_organization_id"), table_name="purchase_orders")
    op.drop_column("purchase_orders", "organization_id")

    op.drop_constraint("fk_recipe_items_org_component_product", "recipe_items", type_="foreignkey")
    op.drop_constraint("fk_recipe_items_org_finished_product", "recipe_items", type_="foreignkey")
    op.drop_constraint(
        "fk_recipe_items_organization_id_organizations", "recipe_items", type_="foreignkey"
    )
    op.drop_index(op.f("ix_recipe_items_organization_id"), table_name="recipe_items")
    op.drop_column("recipe_items", "organization_id")

    op.drop_constraint("fk_inventory_state_org_product", "inventory_state", type_="foreignkey")
    op.drop_constraint(
        "fk_inventory_state_organization_id_organizations", "inventory_state", type_="foreignkey"
    )
    op.drop_index(op.f("ix_inventory_state_organization_id"), table_name="inventory_state")
    op.drop_column("inventory_state", "organization_id")

    op.drop_constraint("fk_inventory_events_org_created_by", "inventory_events", type_="foreignkey")
    op.drop_constraint("fk_inventory_events_org_product", "inventory_events", type_="foreignkey")
    op.drop_constraint(
        "fk_inventory_events_organization_id_organizations", "inventory_events", type_="foreignkey"
    )
    op.drop_index(op.f("ix_inventory_events_organization_id"), table_name="inventory_events")
    op.drop_column("inventory_events", "organization_id")
