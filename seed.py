from datetime import date, timedelta
from logger import logger 
from models import Order 
from sqlalchemy.orm import Session
# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
SEED_ORDERS: list[dict] = [
    {
        "order_number": "ORD-00001",
        "customer_name": "Alice Johnson",
        "status": "Delivered",
        "expected_delivery": date.today() - timedelta(days=3),
    },
    {
        "order_number": "ORD-00042",
        "customer_name": "Bob Martinez",
        "status": "Shipped",
        "expected_delivery": date.today() + timedelta(days=2),
    },
    {
        "order_number": "ORD-00099",
        "customer_name": "Carol White",
        "status": "Processing",
        "expected_delivery": date.today() + timedelta(days=5),
    },
    {
        "order_number": "ORD-00777",
        "customer_name": "David Kim",
        "status": "Out for Delivery",
        "expected_delivery": date.today(),
    },
    {
        "order_number": "ORD-01234",
        "customer_name": "Eva Chen",
        "status": "Cancelled",
        "expected_delivery": date.today() - timedelta(days=1),
    },
]


def seed_database(db: Session) -> None:
    """Insert demo orders only if the table is empty (idempotent)."""
    if db.query(Order).count() > 0:
        logger.info("Database already has orders – skipping seed.")
        return

    logger.info("Seeding database with %d demo orders…", len(SEED_ORDERS))
    for data in SEED_ORDERS:
        db.add(Order(**data))
    db.commit()
    logger.info("Seed complete.")