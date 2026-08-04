"""
tools.py
--------
Defines the standard tools that our AI assistant can use.
These tools bridge the LLM with:
1. The Postgres/SQLite database (SQL Tool).
2. The ChromaDB vector store (Vector Retrieval Tool).
"""

import logging
from sqlalchemy import Integer, cast

from database import SessionLocal
from models import Order, OrderLine, Product
from vector_service import query_faq

logger = logging.getLogger(__name__)


def _get_latest_order(db, order_number: str) -> Order | None:
    """An order number can have multiple suffixes (revisions/releases); return the latest."""
    return (
        db.query(Order)
        .filter(Order.order_number == order_number)
        .order_by(cast(Order.order_suffix, Integer).desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Tool 1: SQL Database Query
# ---------------------------------------------------------------------------
def query_order_status(order_number: str) -> str:
    """
    Query the SQL database to get the current status and delivery details
    of a customer order using its ERP order number (plain digits, e.g. 1206573).
    """
    logger.info("Tool executed: query_order_status for %s", order_number)

    order_number = order_number.strip().lstrip("#")

    db = SessionLocal()
    try:
        order = _get_latest_order(db, order_number)
        if not order:
            return f"searched_order_number: {order_number}\nfound: false"

        return order.format_order_response()
    except Exception as e:
        logger.error("Error running query_order_status: %s", e)
        return "An error occurred while searching for the order in our database."
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool 2: SQL Database Query — order line items
# ---------------------------------------------------------------------------
def query_order_items(order_number: str) -> str:
    """
    Query the SQL database for the list of products/line items on a customer's
    order (quantities, prices, line totals) using its ERP order number
    (plain digits, e.g. 8060622).
    """
    logger.info("Tool executed: query_order_items for %s", order_number)

    order_number = order_number.strip().lstrip("#")

    db = SessionLocal()
    try:
        order = _get_latest_order(db, order_number)
        if not order:
            return f"searched_order_number: {order_number}\nfound: false"

        lines = (
            db.query(OrderLine)
            .filter(
                OrderLine.order_number == order.order_number,
                OrderLine.order_suffix == order.order_suffix,
            )
            .order_by(cast(OrderLine.line_number, Integer))
            .all()
        )
        if not lines:
            return f"order_number: {order.order_number}\nline_items: none on file"

        parts = [f"order_number: {order.order_number}", f"line_item_count: {len(lines)}"]
        for line in lines:
            parts.append("---")
            parts.append(line.format_line_response())
        return "\n".join(parts)
    except Exception as e:
        logger.error("Error running query_order_items: %s", e)
        return "An error occurred while searching for the order's line items in our database."
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool 3: SQL Database Query — product catalog
# ---------------------------------------------------------------------------
def query_product_info(product_code: str) -> str:
    """
    Query the SQL database for details on a product/item (description,
    category, brand, manufacturer, dimensions, unit of measure) using its
    ERP product code (e.g. GA11757-10).
    """
    logger.info("Tool executed: query_product_info for %s", product_code)

    product_code = product_code.strip()

    db = SessionLocal()
    try:
        product = (
            db.query(Product)
            .filter(Product.product_code.ilike(product_code))
            .order_by(Product.company_no)
            .first()
        )
        if not product:
            # Fall back to a partial match in case the user gave a
            # fragment of the code rather than the exact value.
            candidates = (
                db.query(Product)
                .filter(Product.product_code.ilike(f"%{product_code}%"))
                .order_by(Product.company_no)
                .limit(5)
                .all()
            )
            if not candidates:
                return f"searched_product_code: {product_code}\nfound: false"
            if len(candidates) == 1:
                return candidates[0].format_product_response()

            codes = ", ".join(c.product_code for c in candidates)
            return (
                f"searched_product_code: {product_code}\n"
                f"found: false\n"
                f"closest_matches: {codes}"
            )

        return product.format_product_response()
    except Exception as e:
        logger.error("Error running query_product_info: %s", e)
        return "An error occurred while searching for the product in our database."
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool 4: Semantic FAQ Vector Query
# ---------------------------------------------------------------------------
def query_faq_store_policy(user_query: str) -> str:
    """
    Query the store's knowledge base (ChromaDB Vector Store) to retrieve
    information regarding shipping times, shipping costs, return policies, 
    refund timelines, or account password recovery.
    """
    logger.info("Tool executed: query_faq_store_policy for '%s'", user_query)
    
    try:
        # Query ChromaDB FAQ collection for the single best match
        matches = query_faq(user_query, n_results=1)
        if not matches:
            return (
                "I couldn't find any direct policy matching that question. "
                "Let me look up additional information or escalate this for you."
            )
        
        match = matches[0]
        # Return the matching policy text
        return match["document"]
    except Exception as e:
        logger.error("Error running query_faq_store_policy: %s", e)
        return "An error occurred while retrieving information from the store policy FAQs."
