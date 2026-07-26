from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    sku = Column(String, unique=True, index=True)

    # Free-text display label (e.g. "g", "ml", "each") — not a unit-of-
    # measure/conversion system. Recipe quantities (RecipeItem.quantity)
    # are always expressed in this unit; there's no cross-unit conversion,
    # by design, matching the rest of the schema's plain-integer quantities.
    unit = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
