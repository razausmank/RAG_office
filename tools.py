"""
tools.py
--------
Defines the standard tools that our AI assistant can use.
These tools bridge the LLM with:
1. The Postgres/SQLite database (SQL Tool).
2. The ChromaDB vector store (Vector Retrieval Tool).
"""

import logging
from database import SessionLocal
from models import Order
from vector_service import query_faq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool 1: SQL Database Query
# ---------------------------------------------------------------------------
def query_order_status(order_number: str) -> str:
    """
    Query the SQL database to get the current status and delivery details
    of a customer order using its canonical ORD-XXXXX number.
    """
    logger.info("Tool executed: query_order_status for %s", order_number)
    
    # Normalize order number format (case-insensitive, zero-filled)
    order_number = order_number.strip().upper()
    if not order_number.startswith("ORD-") and order_number.isdigit():
        order_number = f"ORD-{order_number.zfill(5)}"

    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_number).first()
        if not order:
            return (
                f"I couldn't find any order with the number **{order_number}** in our system. "
                "Please verify the order number and try again."
            )

       
        return order.format_order_response()
    except Exception as e:
        logger.error("Error running query_order_status: %s", e)
        return "An error occurred while searching for the order in our database."
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool 2: Semantic FAQ Vector Query
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
