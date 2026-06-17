"""
agent.py
--------
Compiles the stateful LangGraph Agent.
It imports the SQL database and ChromaDB tools, binds them to the ChatOllama model,
and compiles a state graph that handles tool routing automatically.
"""

import logging
from collections.abc import AsyncIterator

from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from tools import query_order_status, query_faq_store_policy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MODEL: str = "llama3.2:latest"          # Needs to match Ollama settings
REQUEST_TIMEOUT: float = 120.0

# Injected system instruction guiding the model on how/when to use tools.
SYSTEM_PROMPT: str = (
    "You are a helpful and friendly customer-service assistant for our online store. "
    "Answer questions about products, returns, shipping policies, and general inquiries. "
    "Be concise, professional, and empathetic. "
    "You have access to the following tools:\n"
    "1. Use 'query_order_status' to lookup status, expected delivery, and details of a customer's order. "
    "Always ask for the order number (e.g., ORD-00042) if the user is asking about their order but didn't provide one.\n"
    "2. Use 'query_faq_store_policy' to search store policies (shipping times, shipping cost, refunds, returns, or password reset).\n\n"
    "If you cannot answer the question using the tools, say so honestly and offer to escalate to support."
)

# ---------------------------------------------------------------------------
# Model & Agent Compilation
# ---------------------------------------------------------------------------

# Initialize the chat model
llm = ChatOllama(
    base_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=0.0,
    timeout=REQUEST_TIMEOUT,
)

# List of tools available to the agent
tools = [query_order_status, query_faq_store_policy]

# Compile the ReAct agent graph.
# prompt acts as the System Prompt.
agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt=SYSTEM_PROMPT
)


# ---------------------------------------------------------------------------
# Streaming Runner
# ---------------------------------------------------------------------------
async def stream_agent_response(user_message: str) -> AsyncIterator[str]:
    """
    Stream inputs through the LangGraph agent graph. Yields text response tokens
    and status notifications (e.g. tool execution notifications) in real-time.
    """
    input_state = {"messages": [("user", user_message)]}

    try:
        # astream_events yields granular lifecycle updates for all nodes in the graph
        async for event in agent.astream_events(input_state, version="v2"):
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
