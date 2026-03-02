"""Standalone FastMCP server — item CRUD tools with JWT RBAC.

This server runs as a separate Docker container (port 8001) and is
completely independent of the Google ADK application.  The ADK agent
connects via the SSE endpoint exposed by FastAPI below.

Auth pattern
------------
Every tool accepts an optional ``auth_token`` parameter.  When the ADK
agent calls a tool it injects the caller's JWT so the MCP server can
validate permissions without coupling to the main app's auth layer.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastmcp import FastMCP

mcp = FastMCP(
    name="item-management-mcp",
    instructions=(
        "This MCP server provides item CRUD operations with RBAC. "
        "Pass your JWT as `auth_token` when calling write/delete tools."
    ),
)

# ---------------------------------------------------------------------------
# Auth helpers (inline, no shared lib dependency)
# ---------------------------------------------------------------------------

def _validate_token(token: str) -> Dict[str, Any]:
    """Decode the JWT and return the payload, or raise PermissionError."""
    import os
    from jose import JWTError, jwt  # type: ignore

    secret = os.getenv("JWT_SECRET_KEY", "")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")

    if not secret:
        raise PermissionError("JWT_SECRET_KEY not configured on MCP server")

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except JWTError as exc:
        raise PermissionError(f"Invalid token: {exc}") from exc


def _require_permission(token: str, permission: str) -> Dict[str, Any]:
    """Validate token and assert the required permission is present."""
    if not token:
        raise PermissionError("Authentication required: provide auth_token")

    payload = _validate_token(token)
    permissions: List[str] = payload.get("permissions", [])

    if permission not in permissions:
        raise PermissionError(
            f"Permission denied: '{permission}' required "
            f"(your permissions: {permissions})"
        )

    return payload


# ---------------------------------------------------------------------------
# Shared in-process item store (backed by the app's MongoDB in production;
# the standalone server uses its own motor connection for independence)
# ---------------------------------------------------------------------------

def _get_db():
    """Return the motor database handle (lazily connected)."""
    import os
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

    mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    database = os.getenv("MONGODB_DATABASE", "adk_demo")

    client = AsyncIOMotorClient(mongo_url)
    return client[database]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

def _doc_to_dict(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


@mcp.tool()
async def list_items(
    limit: int = 50,
    auth_token: str = "",
) -> List[Dict[str, Any]]:
    """List all items in the system.

    Requires permission: items:read
    """
    _require_permission(auth_token, "items:read")

    db = _get_db()
    cursor = db.items.find().limit(limit)
    results = []
    async for doc in cursor:
        results.append(_doc_to_dict(doc))
    return results


@mcp.tool()
async def read_item(
    item_id: str,
    auth_token: str = "",
) -> Dict[str, Any]:
    """Read a single item by its ID.

    Requires permission: items:read
    """
    _require_permission(auth_token, "items:read")

    from bson import ObjectId  # type: ignore

    db = _get_db()
    doc = await db.items.find_one({"_id": ObjectId(item_id)})
    if not doc:
        return {"error": f"Item {item_id} not found"}

    return _doc_to_dict(doc)


@mcp.tool()
async def create_item(
    name: str,
    description: str = "",
    data: str = "{}",
    owner_id: str = "",
    auth_token: str = "",
) -> Dict[str, Any]:
    """Create a new item.

    ``data`` should be a JSON-encoded string representing arbitrary metadata.

    Requires permission: items:write
    """
    payload = _require_permission(auth_token, "items:write")
    effective_owner = owner_id or payload.get("sub", "unknown")

    import json as _json

    try:
        data_dict = _json.loads(data) if data else {}
    except _json.JSONDecodeError:
        data_dict = {}

    db = _get_db()
    now = datetime.now(timezone.utc)
    item_doc = {
        "name": name,
        "description": description,
        "data": data_dict,
        "owner_id": effective_owner,
        "created_at": now,
        "updated_at": now,
    }

    result = await db.items.insert_one(item_doc)
    return {
        "id": str(result.inserted_id),
        "name": name,
        "description": description,
        "owner_id": effective_owner,
        "created_at": now.isoformat(),
        "status": "created",
    }


@mcp.tool()
async def update_item(
    item_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    data: Optional[str] = None,
    auth_token: str = "",
) -> Dict[str, Any]:
    """Update an existing item.

    Only non-None fields are updated.

    Requires permission: items:write
    """
    _require_permission(auth_token, "items:write")

    from bson import ObjectId  # type: ignore
    import json as _json

    updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if data is not None:
        try:
            updates["data"] = _json.loads(data)
        except _json.JSONDecodeError:
            updates["data"] = {}

    db = _get_db()
    result = await db.items.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": updates},
    )

    if result.matched_count == 0:
        return {"error": f"Item {item_id} not found"}

    return {"id": item_id, "updated_fields": list(updates.keys()), "status": "updated"}


@mcp.tool()
async def delete_item(
    item_id: str,
    auth_token: str = "",
) -> Dict[str, Any]:
    """Delete an item by ID.

    Requires permission: items:delete
    """
    _require_permission(auth_token, "items:delete")

    from bson import ObjectId  # type: ignore

    db = _get_db()
    result = await db.items.delete_one({"_id": ObjectId(item_id)})

    if result.deleted_count == 0:
        return {"error": f"Item {item_id} not found"}

    return {"id": item_id, "status": "deleted"}
