"""
llm_service.py
--------------
Isolated, dependency-free module for communicating with a local Ollama instance.

Design decisions
----------------
* Uses httpx (async-first) so it integrates cleanly with FastAPI's async event loop.
* Supports Ollama's streaming NDJSON protocol so the caller can forward chunks
  to the browser in real-time without buffering the whole response.
* Gracefully handles the two most common failure modes:
    1. Ollama is not running (connection refused / timeout).
    2. Ollama returns a non-200 HTTP status.
"""

import logging
from collections.abc import AsyncIterator

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MODEL: str = "llama3.2:latest"          # swap to "mistral" or any pulled model
REQUEST_TIMEOUT: float = 120.0         # seconds

# System prompt injected into every conversation so the LLM stays in character
SYSTEM_PROMPT: str = (
    "You are a helpful and friendly customer-service assistant for our online store. "
    "Answer questions about products, returns, shipping policies, and general inquiries. "
    "Be concise, professional, and empathetic. "
    "If you do not know the answer, say so honestly and offer to escalate."
)

# Initialize LangChain ChatOllama Client
# Setting timeout, base_url, and model directly.
llm = ChatOllama(
    base_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=0.0,
    timeout=REQUEST_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def stream_llm_response(user_message: str) -> AsyncIterator[str]:
    """
    Send *user_message* to the local Ollama instance using LangChain and yield 
    response text chunks as they arrive (streaming mode).

    Yields
    ------
    str
        Individual text fragments from the model response.
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    try:
        # astream yields ChatMessageChunk objects. We yield the text content.
        async for chunk in llm.astream(messages):
            if chunk.content:
                yield chunk.content

    except Exception as exc:
        logger.error("Error communicating with Ollama: %s", exc)
        raise RuntimeError(
            "The AI assistant took too long to respond or is unreachable. "
            "Please try again or contact support."
        ) from exc


async def get_llm_response(user_message: str) -> str:
    """
    Non-streaming convenience wrapper – collects all chunks and returns a
    single string.  Useful for testing or for endpoints that don't support SSE.
    """
    parts: list[str] = []
    async for chunk in stream_llm_response(user_message):
        parts.append(chunk)
    return "".join(parts)
