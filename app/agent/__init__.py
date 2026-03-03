"""Agent package - LangGraph-based orchestration.

This package provides AI agent functionality using LangGraph framework:
- graph.py: LangGraphOrchestrator with MongoDB checkpointing
- nodes.py: Node implementations (planner, executor, summary)
- state.py: TypedDict state definitions
- tools.py: MCP tool integration
- ai_service.py: Vertex AI integration

All checkpointing is handled by LangGraph with MongoDB.
"""

from app.agent.graph import LangGraphOrchestrator, get_orchestrator

__all__ = ["LangGraphOrchestrator", "get_orchestrator"]
