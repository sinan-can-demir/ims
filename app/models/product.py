from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    # Composite-FK target for org-scoped children (inventory_events,
    # recipe_items, purchase_order_lines, etc. — Epoch 10). id itself
    # stays a plain, globally-unique PK across every org (see ROADMAP.md's
    # EPOCH 10 section) — this is an *additional* uniqueness guarantee for
    # the composite-FK shape, not a replacement for it.
    #
    # uq_products_org_sku (Epoch 10 PR 6, see migrations/versions/
    # ffdda217be31): sku moved from globally-unique to
    # UNIQUE(organization_id, sku) — two orgs can now share a sku string.
    # get_product_by_sku() is org-scoped as of Epoch 10 PR 7 (#143).
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_products_org_id"),
        UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled to the bootstrap org (id=1) for every pre-Epoch-10 row —
    # see migrations/versions/49570bffe51e. server_default="1" kept
    # permanently (not dropped after backfill): create_product() now
    # threads a real organization_id (Epoch 10 PR 7, #143), but direct-ORM
    # write paths outside the service layer (e.g. scripts/seed_data.py)
    # still rely on this default, same idiom as role/is_active in
    # app/models/user.py. Also needed at this Python level (not just in
    # the migration) so Base.metadata.create_all() — the SQLite test path
    # — creates the same default a real Postgres migration would.
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, server_default="1", index=True
    )

    name = Column(String, nullable=False)

    # No unique=True/index=True here — uniqueness is now org-scoped, see
    # uq_products_org_sku above (that constraint also backs lookups).
    sku = Column(String)

    # Free-text display label (e.g. "g", "ml", "each") — not a unit-of-
    # measure/conversion system. Recipe quantities (RecipeItem.quantity)
    # are always expressed in this unit; there's no cross-unit conversion,
    # by design, matching the rest of the schema's plain-integer quantities.
    unit = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
