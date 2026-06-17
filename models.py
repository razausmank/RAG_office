"""
models.py
---------
ORM model definitions.  All models inherit from `Base` (defined in database.py)
so that `Base.metadata.create_all(engine)` will create every table in one call.
"""

from datetime import date
from sqlalchemy import Integer, String, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Order(Base):
    """
    Represents a customer order.

    Columns
    -------
    id               : Auto-increment PK.
    order_number     : Human-readable order ID, e.g. ORD-00123.  Unique.
    customer_name    : Full name of the customer who placed the order.
    status           : Current order lifecycle stage.
    expected_delivery: Estimated date the order will be delivered.
    """

    __tablename__ = "orders"

    # Enforce uniqueness at the DB level as well as via the ORM constraint
    __table_args__ = (UniqueConstraint("order_number", name="uq_order_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Processing",
        comment="E.g. Processing | Shipped | Out for Delivery | Delivered | Cancelled",
    )
    expected_delivery: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_address: Mapped[str] = mapped_column(String(255), nullable=True) 

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} order_number={self.order_number!r} "
            f"status={self.status!r}>"
        )
