from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    contact_email = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
