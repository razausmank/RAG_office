"""
main.py
-------
FastAPI application entry point.

Startup behaviour
-----------------
1. Creates all DB tables if they don't exist yet.
2. Mounts the `static/` directory so `index.html` is served at the root URL.

The `orders` table itself is populated separately via `import_orders.py`
from the ERP CSV export (too large to load on every app startup).

Chat endpoint logic  (POST /api/chat)
--------------------------------------
The user message is forwarded as-is to the LangGraph agent (agent.py), which
decides whether to call the `query_order_status` tool (looking up an order by
its plain ERP order number, e.g. "1206573") or the FAQ vector-search tool, and
streams the reply back via Server-Sent Events (SSE).
"""


from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from schemas.ChatRequest import ChatRequest
from models import Order
from agent import stream_agent_response
from logger import logger



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
    logger.info("Received message: %r (conversation_id=%s)", user_msg[:120], request.conversation_id)

    async def _agent_stream():
        try:
            async for chunk in stream_agent_response(user_msg, request.conversation_id):
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
