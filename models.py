"""
models.py
---------
ORM model definitions.  All models inherit from `Base` (defined in database.py)
so that `Base.metadata.create_all(engine)` will create every table in one call.
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

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


class OrderLine(Base):
    """
    A single product line on an order, sourced from the ERP's OEEL
    (order-entry line) export. Joins back to `Order` via
    (order_number, order_suffix), matching that table's unique constraint.
    """

    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint(
            "order_number", "order_suffix", "line_number", name="uq_order_line"
        ),
        ForeignKeyConstraint(
            ["order_number", "order_suffix"],
            ["orders.order_number", "orders.order_suffix"],
            name="fk_order_lines_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # ERP source row identity (used to make CSV re-imports idempotent).
    row_pointer: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)

    # Order identity (FK to orders)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    order_suffix: Mapped[str] = mapped_column(String(5), nullable=False, default="0")
    line_number: Mapped[str] = mapped_column(String(10), nullable=False)

    # Product
    product_code: Mapped[str] = mapped_column(String(50), nullable=True)
    product_category: Mapped[str] = mapped_column(String(10), nullable=True)
    product_line: Mapped[str] = mapped_column(String(50), nullable=True)
    unit: Mapped[str] = mapped_column(String(10), nullable=True)

    # Quantities / pricing
    quantity_ordered: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    quantity_shipped: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)

    # Classification (raw ERP codes)
    status_type: Mapped[str] = mapped_column(String(5), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=True)

    # Fulfillment
    warehouse: Mapped[str] = mapped_column(String(10), nullable=True)
    sales_rep_in: Mapped[str] = mapped_column(String(10), nullable=True)
    sales_territory: Mapped[str] = mapped_column(String(10), nullable=True)

    # Dates
    entered_date: Mapped[date] = mapped_column(Date, nullable=True)
    promised_date: Mapped[date] = mapped_column(Date, nullable=True)
    requested_ship_date: Mapped[date] = mapped_column(Date, nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=True)
    cancel_date: Mapped[date] = mapped_column(Date, nullable=True)

    # ERP audit trail
    source_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_modified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    order: Mapped["Order"] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return (
            f"<OrderLine order_number={self.order_number!r} "
            f"line_number={self.line_number!r} product_code={self.product_code!r}>"
        )

    def format_line_response(self) -> str:
        """Plain labeled facts (see Order.format_order_response for why)."""
        return "\n".join(
            [
                f"line_number: {self.line_number}",
                f"product_code: {self.product_code or 'unknown'}",
                f"product_category: {self.product_category or 'n/a'}",
                f"quantity_ordered: {self.quantity_ordered}",
                f"quantity_shipped: {self.quantity_shipped}",
                f"unit_price: {self.unit_price}",
                f"line_total: {self.line_total}",
            ]
        )


class Product(Base):
    """
    A product/item master record, sourced from the ERP's ICSP export.

    The ERP export has ~180 internal columns; this keeps only the fields
    useful for answering customer/catalog questions (what is it, what
    category/unit/dimensions, is it active).

    Unique per (company_no, product_code): the same product code can exist
    as a distinct record under a different company in this multi-company ERP.

    Column widths here are deliberately generous rather than matching the
    ERP data dictionary's declared lengths: real data was found to exceed
    the documented length for several fields (e.g. `prod` is documented as
    x(24) but real values run to 29 chars), so declared lengths aren't
    trustworthy as hard limits — see the OrderLine.taken_by truncation bug
    for why this matters.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("company_no", "product_code", name="uq_product_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # ERP source row identity
    row_pointer: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)

    # Identity
    company_no: Mapped[str] = mapped_column(String(5), nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    lookup_name: Mapped[str] = mapped_column(String(60), nullable=True)

    # Description
    description_1: Mapped[str] = mapped_column(String(60), nullable=True)
    description_2: Mapped[str] = mapped_column(String(60), nullable=True)
    description_extended: Mapped[str] = mapped_column(Text, nullable=True)

    # Classification (raw ERP codes)
    category: Mapped[str] = mapped_column(String(10), nullable=True)
    product_type: Mapped[str] = mapped_column(String(5), nullable=True)
    status_code: Mapped[str] = mapped_column(String(5), nullable=True)
    brand_code: Mapped[str] = mapped_column(String(10), nullable=True)

    # Manufacturer / model
    manufacturer_product: Mapped[str] = mapped_column(String(60), nullable=True)
    model_code: Mapped[str] = mapped_column(String(30), nullable=True)

    # Units of measure
    stocking_unit: Mapped[str] = mapped_column(String(10), nullable=True)
    selling_unit: Mapped[str] = mapped_column(String(10), nullable=True)
    counting_unit: Mapped[str] = mapped_column(String(10), nullable=True)

    # Physical dimensions
    weight: Mapped[float] = mapped_column(Numeric(14, 5), nullable=True)
    height: Mapped[float] = mapped_column(Numeric(14, 5), nullable=True)
    width: Mapped[float] = mapped_column(Numeric(14, 5), nullable=True)
    length: Mapped[float] = mapped_column(Numeric(14, 5), nullable=True)
    cubes: Mapped[float] = mapped_column(Numeric(14, 5), nullable=True)

    # Trade / compliance
    country_of_origin: Mapped[str] = mapped_column(String(5), nullable=True)
    warranty_type: Mapped[str] = mapped_column(String(5), nullable=True)
    warranty_length: Mapped[int] = mapped_column(Integer, nullable=True)
    tariff_code: Mapped[str] = mapped_column(String(20), nullable=True)
    unspsc: Mapped[str] = mapped_column(String(20), nullable=True)

    # Dates
    entered_date: Mapped[date] = mapped_column(Date, nullable=True)
    last_change_date: Mapped[date] = mapped_column(Date, nullable=True)

    # ERP audit trail
    source_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    erp_modified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Product company_no={self.company_no!r} "
            f"product_code={self.product_code!r} status_code={self.status_code!r}>"
        )

    def format_product_response(self) -> str:
        """Plain labeled facts (see Order.format_order_response for why)."""
        description = " ".join(p for p in [self.description_1, self.description_2] if p)
        return "\n".join(
            [
                f"product_code: {self.product_code}",
                f"description: {description or 'unknown'}",
                f"category: {self.category or 'n/a'}",
                f"product_type: {self.product_type or 'n/a'}",
                f"status_code: {self.status_code or 'n/a'}",
                f"brand_code: {self.brand_code or 'n/a'}",
                f"manufacturer_product: {self.manufacturer_product or 'n/a'}",
                f"stocking_unit: {self.stocking_unit or 'n/a'}",
                f"selling_unit: {self.selling_unit or 'n/a'}",
                f"weight: {self.weight}",
                f"dimensions_lwh: {self.length}x{self.width}x{self.height}",
                f"country_of_origin: {self.country_of_origin or 'n/a'}",
            ]
        )
