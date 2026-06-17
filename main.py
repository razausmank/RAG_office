"""
main.py
-------
FastAPI application entry point.

Startup behaviour
-----------------
1. Creates all DB tables if they don't exist yet.
2. Seeds the `orders` table with demo data (idempotent – skips if already present).
3. Mounts the `static/` directory so `index.html` is served at the root URL.

Chat endpoint logic  (POST /api/chat)
--------------------------------------
1. Regex-scan the user message for an order number:
      - Explicit format : ORD-XXXXX   (e.g. "ORD-00042")
      - Bare digits      : 6-8 consecutive digits (e.g. "123456")
2. If found → query the DB and return a structured plain-text response.
3. If not found → forward the message to Ollama and stream the reply back via
   Server-Sent Events (SSE), so the browser can render tokens as they arrive.
"""


from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from models import Order
from agent import stream_agent_response
from logger import logger 
from seed import seed_database



# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Customer Service Chatbot API",
    description=(
        "Routes order-number queries to the local SQL database and "
        "general inquiries to a local Ollama LLM."
    ),
    version="1.0.0",
)

# Allow requests from the browser when the frontend is served separately
# (e.g. during development with a Vite dev server).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten this in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    """Seed demo data on first run if database is empty."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's chat message.",
        examples=["Where is my order ORD-00042?"],
    )


# ---------------------------------------------------------------------------
# Helper: format an order record into a human-readable reply
# ---------------------------------------------------------------------------
def _format_order_response(order: Order) -> str:
    delivery_str = (
        order.expected_delivery.strftime("%B %d, %Y")
        if order.expected_delivery
        else "unknown"
    )

    status_emoji: dict[str, str] = {
        "Processing": "⏳",
        "Shipped": "📦",
        "Out for Delivery": "🚚",
        "Delivered": "✅",
        "Cancelled": "❌",
    }
    emoji = status_emoji.get(order.status, "ℹ️")

    return (
        f"Here's the latest info on **{order.order_number}**:\n\n"
        f"{emoji} **Status:** {order.status}\n"
        f"👤 **Customer:** {order.customer_name}\n"
        f"📅 **Expected Delivery:** {delivery_str}\n\n"
        f"Is there anything else I can help you with?"
    )


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------
@app.post(
    "/api/chat",
    summary="Send a chat message",
    response_description=(
        "An SSE stream of final response tokens and tool trigger updates."
    ),
)
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Routes the user message directly to the stateful LangGraph Agent.
    The agent determines which tools to call (SQL order query or Vector FAQ retrieval)
    and streams the response tokens back via Server-Sent Events (SSE).
    """
    user_msg = request.message.strip()
    logger.info("Received message: %r", user_msg[:120])

    async def _agent_stream():
        try:
            async for chunk in stream_agent_response(user_msg):
                # SSE format: escape literal newlines inside chunk text so SSE framing holds
                safe_chunk = chunk.replace("\n", "\\n")
                yield f"data: {safe_chunk}\n\n"
        except Exception as exc:
            # Catch any agent exceptions and stream a friendly error
            error_msg = str(exc).replace("\n", "\\n")
            yield f"data: ⚠️ {error_msg}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(_agent_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


# ---------------------------------------------------------------------------
# Serve the frontend
# Static files are mounted LAST so API routes take priority.
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
