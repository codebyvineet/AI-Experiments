"""CRUD API routes for items."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends

from app.auth import get_current_user, require_permission
from app.crud import item_crud
from app.models import Item, ItemCreate, ItemUpdate, TokenData

router = APIRouter(prefix="/items", tags=["items"])


@router.post("/", response_model=Item)
async def create_item(
    item_data: ItemCreate,
    current_user: TokenData = Depends(require_permission("items:write"))
):
    """Create a new item."""
    item = await item_crud.create_item(item_data, current_user.user_id)
    return item


@router.get("/", response_model=List[Item])
async def list_items(
    skip: int = 0,
    limit: int = 100,
    my_items_only: bool = False,
    current_user: TokenData = Depends(require_permission("items:read"))
):
    """List all items or only user's items."""
    owner_id = current_user.user_id if my_items_only else None
    items = await item_crud.list_items(owner_id=owner_id, skip=skip, limit=limit)
    return items


@router.get("/{item_id}", response_model=Item)
async def get_item(
    item_id: str,
    current_user: TokenData = Depends(require_permission("items:read"))
):
    """Get a specific item by ID."""
    item = await item_crud.get_item(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return item


@router.put("/{item_id}", response_model=Item)
async def update_item(
    item_id: str,
    item_data: ItemUpdate,
    current_user: TokenData = Depends(require_permission("items:write"))
):
    """Update an item (only owner can update)."""
    item = await item_crud.update_item(item_id, item_data, current_user.user_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found or you don't have permission to update it"
        )
    return item


@router.delete("/{item_id}")
async def delete_item(
    item_id: str,
    current_user: TokenData = Depends(require_permission("items:delete"))
):
    """Delete an item (only owner can delete)."""
    deleted = await item_crud.delete_item(item_id, current_user.user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found or you don't have permission to delete it"
        )
    return {"status": "deleted", "item_id": item_id}
