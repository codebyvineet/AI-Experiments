"""Registry package for MCP Server.

Contains MongoDB-backed registries for:
- Tools
- Prompts (future)
- Workflows (future)
"""

from .tool_registry import ToolRegistry, tool_registry

__all__ = ["ToolRegistry", "tool_registry"]
