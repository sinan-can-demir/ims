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
    # get_product_by_sku() still queries by sku alone, unscoped, until
    # product_service.py is org-threaded in a later PR (#143); safe until
    # then since nothing can create a product outside org 1 yet.
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_products_org_id"),
        UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Backfilled to the bootstrap org (id=1) for every pre-Epoch-10 row —
    # see migrations/versions/49570bffe51e. server_default="1" kept
    # permanently (not dropped after backfill) since product_service.py
    # doesn't thread organization_id through create_product() until a
    # later Epoch 10 PR — every write path relies on this default until
    # then, same idiom as role/is_active in app/models/user.py. Also
    # needed at this Python level (not just in the migration) so
    # Base.metadata.create_all() — the SQLite test path — creates the
    # same default a real Postgres migration would. sku's uniqueness
    # stays global here; it becomes UNIQUE(organization_id, sku) in a
    # later Epoch 10 PR alongside the service/route layer that depends on
    # it, not in this purely-additive schema PR.
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
