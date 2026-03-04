"""ReAct Chat Agent using LangGraph prebuilt + MCP tools.

Uses framework methods exclusively:
- langgraph.prebuilt.create_react_agent for the ReAct loop
- langchain_google_vertexai.ChatVertexAI for the LLM
- app.mcp.client.create_mcp_client for MCP tool binding

No custom ReAct logic — the framework handles think→act→observe→respond.
"""

import asyncio
import json
from typing import Dict, Any, AsyncGenerator, List, Optional

from langchain_google_vertexai import ChatVertexAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient
from google.oauth2 import service_account

from app.config.settings import get_settings
from app.config.logging_config import get_logger
from app.mcp.client import create_mcp_client

logger = get_logger("react_agent")

# Lazy-initialized checkpointer for conversation history
_chat_checkpointer = None


def _get_chat_checkpointer() -> MongoDBSaver:
    """Get or create the MongoDB checkpointer for chat conversation history."""
    global _chat_checkpointer
    if _chat_checkpointer is None:
        settings = get_settings()
        client = MongoClient(settings.mongodb_url)
        _chat_checkpointer = MongoDBSaver(client, db_name=settings.mongodb_database)
    return _chat_checkpointer


def _get_chat_model() -> ChatVertexAI:
    """Create a ChatVertexAI instance from app settings."""
    settings = get_settings()

    kwargs: Dict[str, Any] = {
        "model_name": settings.vertexai_model,
        "project": settings.google_cloud_project,
        "location": settings.google_cloud_location,
        "temperature": 0,
        "max_output_tokens": 4096,
    }

    if settings.google_application_credentials:
        kwargs["credentials"] = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials
        )

    return ChatVertexAI(**kwargs)


def _extract_text_content(content) -> str:
    """Extract plain text from LangChain message content (handles Gemini list-of-blocks format)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content) if content else ""


async def get_chat_history(user_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve conversation history for a user from the LangGraph checkpointer.

    Returns a list of message dicts matching the frontend chatMessages format:
      {"role": "user",      "content": "..."}
      {"role": "assistant", "content": "..."}
      {"role": "tool",      "tool": "...", "content": "...", "toolType": "call"}
      {"role": "tool",      "tool": "...", "content": "...", "toolType": "result"}
    """
    thread_id = f"chat-{user_id}"
    checkpointer = _get_chat_checkpointer()
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    # MongoDBSaver.get() is synchronous — run in executor to avoid blocking event loop
    checkpoint_tuple = await asyncio.get_event_loop().run_in_executor(
        None, lambda: checkpointer.get(config)
    )

    if not checkpoint_tuple:
        return []

    # MongoDBSaver.get() returns the Checkpoint dict directly (not a CheckpointTuple)
    channel_values = checkpoint_tuple.get("channel_values", {})
    raw_messages = channel_values.get("messages", [])

    result = []
    for msg in raw_messages:
        msg_type = getattr(msg, "type", None)
        content = getattr(msg, "content", "")

        if msg_type == "human":
            text = _extract_text_content(content)
            if text:
                result.append({"role": "user", "content": text})

        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    result.append({
                        "role": "tool",
                        "content": f"🔧 Calling **{tc['name']}**({json.dumps(tc.get('args', {}))})",
                        "tool": tc["name"],
                        "toolType": "call",
                    })
            else:
                text = _extract_text_content(content)
                if text:
                    result.append({"role": "assistant", "content": text})

        elif msg_type == "tool":
            result.append({
                "role": "tool",
                "content": str(content)[:2000],
                "tool": getattr(msg, "name", "tool") or "tool",
                "toolType": "result",
            })

    return result


async def chat_stream(
    message: str,
    token: str,
    user_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream a ReAct chat interaction using LangGraph's prebuilt agent.

    Uses agent.astream(stream_mode="updates") to get per-node outputs.
    The ReAct agent alternates between:
      - "agent" node: LLM reasoning (may include tool_calls or final text)
      - "tools" node: MCP tool execution results

    Yields SSE-friendly dicts:
      {"type": "thinking",    "message": "..."}
      {"type": "tool_call",   "tool": "...", "args": {...}}
      {"type": "tool_result", "tool": "...", "result": {...}}
      {"type": "response",    "message": "..."}
      {"type": "error",       "error": "..."}
    """
    # Use user_id as thread_id for conversation history (one thread per user)
    thread_id = f"chat-{user_id}"
    logger.info(f"[Chat] Starting ReAct chat for user={user_id} thread={thread_id}: {message[:80]}")

    yield {"type": "thinking", "message": "Connecting to MCP tools..."}

    try:
        model = _get_chat_model()
    except Exception as e:
        logger.error(f"[Chat] Failed to create ChatVertexAI: {e}")
        yield {"type": "error", "error": f"AI model init failed: {e}"}
        return

    try:
        mcp = create_mcp_client(token)
        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        logger.info(f"[Chat] Loaded {len(tools)} MCP tools: {tool_names}")

        yield {
            "type": "thinking",
            "message": f"Loaded {len(tools)} tools: {', '.join(tool_names)}",
        }

        # Build the ReAct agent with system prompt to encourage tool usage
        system_prompt = (
            "You are a helpful AI assistant with access to a database of items via MCP tools. "
            "ALWAYS use the available tools to answer questions — do not guess or refuse. "
            "For questions about items, counts, or data, call list_items or search_items first, "
            "then analyze the results and give a clear, detailed answer with actual numbers."
        )
        agent = create_react_agent(
            model, tools, prompt=system_prompt,
            checkpointer=_get_chat_checkpointer(),
        )

        final_response = None

        # Stream node-by-node updates with recursion limit to prevent infinite loops
        async for chunk in agent.astream(
            {"messages": [("user", message)]},
            stream_mode="updates",
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
        ):
            for _, node_output in chunk.items():
                messages = node_output.get("messages", [])
                for msg in messages:
                    if msg.type == "ai":
                        # LLM decided something
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                logger.info(f"[Chat] Tool call: {tc['name']}({json.dumps(tc.get('args', {}), default=str)[:200]})")
                                yield {
                                    "type": "tool_call",
                                    "tool": tc["name"],
                                    "args": tc.get("args", {}),
                                }
                        elif msg.content:
                            # Extract text from content (may be str, list of blocks, etc.)
                            content = msg.content
                            if isinstance(content, list):
                                # Gemini returns list of content blocks
                                text_parts = []
                                for part in content:
                                    if isinstance(part, dict) and "text" in part:
                                        text_parts.append(part["text"])
                                    elif isinstance(part, str):
                                        text_parts.append(part)
                                final_response = "\n".join(text_parts)
                            elif isinstance(content, str):
                                final_response = content
                            else:
                                final_response = str(content)

                    elif msg.type == "tool":
                        # Tool execution result
                        result_str = str(msg.content)[:2000] if msg.content else ""
                        logger.info(f"[Chat] Tool result: {msg.name} -> {result_str[:200]}")
                        yield {
                            "type": "tool_result",
                            "tool": msg.name or "unknown",
                            "result": result_str,
                        }

        # Yield the final response
        if final_response:
            yield {"type": "response", "message": final_response}
        else:
            yield {"type": "response", "message": "No response generated."}

    except Exception as e:
        logger.error(f"[Chat] ReAct agent error: {e}", exc_info=True)
        yield {"type": "error", "error": str(e)}

    logger.info(f"[Chat] Completed for user={user_id}")
