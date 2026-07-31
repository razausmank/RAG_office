"""
models.py
---------
ORM model definitions.  All models inherit from `Base` (defined in database.py)
so that `Base.metadata.create_all(engine)` will create every table in one call.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Order(Base):
    """
    A customer order, sourced from the ERP's OEEH (order-entry header) export.

    The ERP export has 400+ internal columns (tax breakdowns, ERP flags,
    stack traces, ...); this table keeps only the fields needed to answer
    customer-facing questions about an order (who, what, where, when, status).

    `status_code` is the raw ERP disposition code (e.g. "s", "S", "t", "W").
    Its meaning isn't documented, so a human-friendly status is derived at
    display time from the unambiguous date fields instead of decoding it —
    see `format_order_response()`.
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number", "order_suffix", name="uq_order_number_suffix"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # ERP source row identity (used to make CSV re-imports idempotent).
    row_pointer: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)

    # Order identity
    order_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    order_suffix: Mapped[str] = mapped_column(String(5), nullable=False, default="0")

    # Customer / ship-to
    customer_no: Mapped[str] = mapped_column(String(20), nullable=True)
    customer_po: Mapped[str] = mapped_column(String(100), nullable=True)
    ship_to_no: Mapped[str] = mapped_column(String(10), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=True)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)

    # Delivery address
    address_line1: Mapped[str] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str] = mapped_column(String(255), nullable=True)
    address_line3: Mapped[str] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=True)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(5), nullable=True)

    # Status / classification (raw ERP codes)
    status_code: Mapped[str] = mapped_column(String(10), nullable=True)
    backorder_stage: Mapped[str] = mapped_column(String(5), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=True)
    order_source: Mapped[str] = mapped_column(String(50), nullable=True)

    # Dates
    entered_date: Mapped[date] = mapped_column(Date, nullable=True)
    promised_date: Mapped[date] = mapped_column(Date, nullable=True)
    requested_ship_date: Mapped[date] = mapped_column(Date, nullable=True)
    ship_date: Mapped[date] = mapped_column(Date, nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=True)
    cancel_date: Mapped[date] = mapped_column(Date, nullable=True)

    # Totals
    total_order_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    total_line_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    total_invoice_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    total_qty_ordered: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    total_qty_shipped: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)

    # Fulfillment / handling
    ship_via: Mapped[str] = mapped_column(String(10), nullable=True)
    warehouse: Mapped[str] = mapped_column(String(10), nullable=True)
    taken_by: Mapped[str] = mapped_column(String(50), nullable=True)
    sales_rep_in: Mapped[str] = mapped_column(String(10), nullable=True)
    terms_type: Mapped[str] = mapped_column(String(10), nullable=True)

    # ERP audit trail
    source_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_modified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} order_number={self.order_number!r} "
            f"status_code={self.status_code!r}>"
        )

    def _display_status(self) -> str:
        """Derive a human-friendly status from the unambiguous date fields."""
        if self.cancel_date:
            return "Cancelled"
        if self.invoice_date:
            return "Delivered"
        if self.ship_date:
            return "Shipped"
        return "Processing"

    def format_order_response(self) -> str:
        """
        Return the order's data as plain labeled facts, not a phrased reply.

        Deliberately not written in assistant voice (no greeting, no sign-off,
        no markdown emphasis): a tool result that already reads like a
        finished chat reply gets misread by some models as "already sent to
        the user", causing them to skip relaying it and just say "I already
        answered". Plain data forces the model to compose the actual reply.
        """
        status = self._display_status()
        promised_str = (
            self.promised_date.strftime("%B %d, %Y") if self.promised_date else "unknown"
        )
        address_parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.postal_code,
        ]
        address = ", ".join(p for p in address_parts if p) or "unknown"

        return "\n".join(
            [
                f"order_number: {self.order_number}",
                f"status: {status} (ERP code: {self.status_code or 'n/a'})",
                f"customer_name: {self.customer_name or 'unknown'}",
                f"promised_delivery: {promised_str}",
                f"delivery_address: {address}",
            ]
        )
