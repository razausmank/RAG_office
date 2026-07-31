"""
agent.py
--------
Compiles the stateful LangGraph Agent.
It imports the SQL database and ChromaDB tools, binds them to the Groq-hosted
chat model, and compiles a state graph that handles tool routing automatically.
"""

import logging
import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from tools import query_order_status, query_faq_store_policy

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GROQ_MODEL: str = "llama-3.3-70b-versatile"  # Must be a tool-calling-capable Groq model
REQUEST_TIMEOUT: float = 120.0

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Add it to your .env file (get one at "
        "https://console.groq.com/keys)."
    )

# Injected system instruction guiding the model on how/when to use tools.
SYSTEM_PROMPT: str = (
    "You are a helpful and friendly customer-service assistant for our online store. "
    "Answer questions about products, returns, shipping policies, and general inquiries. "
    "Be concise, professional, and empathetic. "
    "You have access to the following tools:\n"
    "1. Use 'query_order_status' to lookup status, expected delivery, and details of a customer's order. "
    "Always ask for the order number (e.g., 1206573) if the user is asking about their order but didn't provide one.\n"
    "2. Use 'query_faq_store_policy' to search store policies (shipping times, shipping cost, refunds, returns, or password reset).\n\n"
    "When a tool returns information, relay that information to the user in full in your reply — "
    "do not just say you've already answered or provided the details; restate them.\n"
    "If you cannot answer the question using the tools, say so honestly and offer to escalate to support."
)

# ---------------------------------------------------------------------------
# Model & Agent Compilation
# ---------------------------------------------------------------------------

# Initialize the chat model
llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL,
    temperature=0.0,
    timeout=REQUEST_TIMEOUT,
)

# List of tools available to the agent
tools = [query_order_status, query_faq_store_policy]

# In-memory conversation store, keyed by thread_id (one per browser chat
# session). State is lost on restart and isn't shared across worker
# processes — fine for a single-process dev/demo deployment.
checkpointer = MemorySaver()

# Compile the ReAct agent graph.
# prompt acts as the System Prompt.
agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)


# ---------------------------------------------------------------------------
# Streaming Runner
# ---------------------------------------------------------------------------
async def stream_agent_response(user_message: str, thread_id: str) -> AsyncIterator[str]:
    """
    Stream inputs through the LangGraph agent graph. Yields text response tokens
    and status notifications (e.g. tool execution notifications) in real-time.

    `thread_id` identifies the conversation: the checkpointer uses it to load
    prior messages in this thread and append the new turn to the same history.
    """
    input_state = {"messages": [("user", user_message)]}
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # astream_events yields granular lifecycle updates for all nodes in the graph
        async for event in agent.astream_events(input_state, config, version="v2"):
            event_type = event["event"]

            # 1. Yield streaming tokens from the LLM chat model
            if event_type == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield content

            # 2. Yield visual feedback when a tool starts running
            elif event_type == "on_tool_start":
                tool_name = event["name"]
                # Map technical tool name to a friendly status message
                friendly_name = tool_name.replace("_", " ").title()
                yield f"\n\n*🔍 Checking {friendly_name}...*\n\n"

    except Exception as exc:
        logger.error("Error in LangGraph agent loop: %s", exc)
        raise RuntimeError(
            "The assistant encountered an error. Please try again later."
        ) from exc
