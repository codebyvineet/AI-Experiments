"""Report generation API routes."""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_permission
from app.models import TokenData
from app.checkpoints import mongodb_checkpoint

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportRequest(BaseModel):
    """Request model for report generation."""
    report_type: str = "summary"
    filters: Optional[Dict[str, Any]] = None


@router.post("/generate")
async def generate_report(
    request: ReportRequest,
    current_user: TokenData = Depends(require_permission("items:read"))
) -> Dict[str, Any]:
    """Generate a report based on type and filters.
    
    Report types:
    - summary: Quick overview of items
    - detailed: Full item details
    - activity: Recent activity report
    """
    db = mongodb_checkpoint.db
    filters = request.filters or {}
    
    if request.report_type == "summary":
        return await _generate_summary_report(db, current_user.user_id, filters)
    elif request.report_type == "detailed":
        return await _generate_detailed_report(db, current_user.user_id, filters)
    elif request.report_type == "activity":
        return await _generate_activity_report(db, current_user.user_id, filters)
    else:
        return {"error": f"Unknown report type: {request.report_type}"}


async def _generate_summary_report(db, user_id: str, filters: dict) -> Dict[str, Any]:
    """Generate a summary report."""
    # Total items
    total = await db.items.count_documents({})
    user_items = await db.items.count_documents({"owner_id": user_id})
    
    # Items by date
    now = datetime.now(timezone.utc)
    today = await db.items.count_documents({
        "created_at": {"$gte": now.replace(hour=0, minute=0, second=0)}
    })
    this_week = await db.items.count_documents({
        "created_at": {"$gte": now - timedelta(days=7)}
    })
    this_month = await db.items.count_documents({
        "created_at": {"$gte": now - timedelta(days=30)}
    })
    
    return {
        "report_type": "summary",
        "generated_at": now.isoformat(),
        "generated_by": user_id,
        "data": {
            "total_items": total,
            "user_items": user_items,
            "created_today": today,
            "created_this_week": this_week,
            "created_this_month": this_month
        }
    }


async def _generate_detailed_report(db, user_id: str, filters: dict) -> Dict[str, Any]:
    """Generate a detailed report with item information."""
    query = {}
    if filters.get("owner_only"):
        query["owner_id"] = user_id
    
    limit = filters.get("limit", 100)
    
    cursor = db.items.find(query).sort("created_at", -1).limit(limit)
    
    items = []
    async for doc in cursor:
        items.append({
            "id": str(doc["_id"]),
            "name": doc.get("name"),
            "description": doc.get("description"),
            "data_keys": list(doc.get("data", {}).keys()) if doc.get("data") else [],
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "owner_id": doc.get("owner_id")
        })
    
    return {
        "report_type": "detailed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": user_id,
        "total_in_report": len(items),
        "items": items
    }


async def _generate_activity_report(db, user_id: str, filters: dict) -> Dict[str, Any]:
    """Generate an activity report."""
    days = filters.get("days", 7)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Items created in period
    cursor = db.items.find({
        "created_at": {"$gte": since}
    }).sort("created_at", -1)
    
    daily_counts = {}
    items = []
    
    async for doc in cursor:
        items.append({
            "id": str(doc["_id"]),
            "name": doc.get("name"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "owner_id": doc.get("owner_id")
        })
        
        # Count by day
        if doc.get("created_at"):
            day_key = doc["created_at"].strftime("%Y-%m-%d")
            daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
    
    return {
        "report_type": "activity",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": user_id,
        "period_days": days,
        "total_activity": len(items),
        "daily_breakdown": daily_counts,
        "recent_items": items[:20]  # Top 20 most recent
    }
