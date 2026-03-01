"""Report and statistics tools for MCP Server."""
import logging
from typing import Any, Dict
from .registry import register_tool
from ..backend_client import backend_client

logger = logging.getLogger(__name__)


# Tool: get_statistics
async def handle_get_statistics(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Get item statistics."""
    logger.info("[get_statistics] Fetching statistics")
    result = await backend_client.get_statistics(token)
    return result


register_tool(
    name="get_statistics",
    description="Get statistics about items in the database (total count, recent activity, etc.)",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    handler=handle_get_statistics,
    category="reports",
    tags=["analytics", "statistics", "metrics"],
    permissions=["items:read"],
    endpoint="/items/stats",
    http_method="GET"
)


# Tool: generate_report
async def handle_generate_report(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Generate a report."""
    report_type = arguments.get("report_type", "summary")
    filters = arguments.get("filters", {})
    
    logger.info(f"[generate_report] Generating report: {report_type}")
    result = await backend_client.generate_report(token, report_type, filters)
    return result


register_tool(
    name="generate_report",
    description="Generate a report about items. Supports different report types: summary, detailed, activity.",
    input_schema={
        "type": "object",
        "properties": {
            "report_type": {
                "type": "string",
                "enum": ["summary", "detailed", "activity"],
                "description": "Type of report to generate (default: summary)"
            },
            "filters": {
                "type": "object",
                "description": "Optional filters to apply (e.g., date range, categories)"
            }
        },
        "required": []
    },
    handler=handle_generate_report,
    category="reports",
    tags=["analytics", "reports", "summary"],
    permissions=["items:read"],
    endpoint="/reports/generate",
    http_method="POST"
)
