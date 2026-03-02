"""CRUD operations for users and items."""

from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId

from app.checkpoints import mongodb_checkpoint
from app.models import User, UserCreate, Item, ItemCreate, ItemUpdate
from app.auth import get_password_hash


class UserCRUD:
    """CRUD operations for users."""
    
    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user."""
        db = mongodb_checkpoint.db
        
        # Check if username or email already exists
        existing = await db.users.find_one({
            "$or": [
                {"username": user_data.username},
                {"email": user_data.email}
            ]
        })
        if existing:
            raise ValueError("Username or email already exists")
        
        user_dict = {
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": get_password_hash(user_data.password),
            "role": user_data.role.value,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        result = await db.users.insert_one(user_dict)
        user_dict["id"] = str(result.inserted_id)
        if "_id" in user_dict:
            del user_dict["_id"]
        
        return User(**user_dict)
    
    async def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        db = mongodb_checkpoint.db
        doc = await db.users.find_one({"_id": ObjectId(user_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return User(**doc)
        return None
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        db = mongodb_checkpoint.db
        doc = await db.users.find_one({"username": username})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return User(**doc)
        return None
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        db = mongodb_checkpoint.db
        doc = await db.users.find_one({"email": email})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return User(**doc)
        return None
    
    async def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List all users."""
        db = mongodb_checkpoint.db
        cursor = db.users.find().skip(skip).limit(limit)
        users = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            users.append(User(**doc))
        return users
    
    async def update_user(self, user_id: str, updates: dict) -> Optional[User]:
        """Update a user."""
        db = mongodb_checkpoint.db
        updates["updated_at"] = datetime.now(timezone.utc)
        
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updates}
        )
        return await self.get_user(user_id)
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        db = mongodb_checkpoint.db
        result = await db.users.delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0


class ItemCRUD:
    """CRUD operations for items."""
    
    async def create_item(self, item_data: ItemCreate, owner_id: str) -> Item:
        """Create a new item."""
        db = mongodb_checkpoint.db
        
        item_dict = {
            "name": item_data.name,
            "description": item_data.description,
            "data": item_data.data,
            "owner_id": owner_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        result = await db.items.insert_one(item_dict)
        item_dict["id"] = str(result.inserted_id)
        
        return Item(**item_dict)
    
    async def get_item(self, item_id: str) -> Optional[Item]:
        """Get item by ID."""
        db = mongodb_checkpoint.db
        doc = await db.items.find_one({"_id": ObjectId(item_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return Item(**doc)
        return None
    
    async def list_items(
        self,
        owner_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Item]:
        """List items, optionally filtered by owner."""
        db = mongodb_checkpoint.db
        
        query = {}
        if owner_id:
            query["owner_id"] = owner_id
        
        cursor = db.items.find(query).skip(skip).limit(limit)
        items = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            items.append(Item(**doc))
        return items
    
    async def update_item(
        self,
        item_id: str,
        item_data: ItemUpdate,
        owner_id: str
    ) -> Optional[Item]:
        """Update an item."""
        db = mongodb_checkpoint.db
        
        # Check ownership
        existing = await db.items.find_one({
            "_id": ObjectId(item_id),
            "owner_id": owner_id
        })
        if not existing:
            return None
        
        updates = item_data.model_dump(exclude_none=True)
        updates["updated_at"] = datetime.now(timezone.utc)
        
        await db.items.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": updates}
        )
        return await self.get_item(item_id)
    
    async def delete_item(self, item_id: str, owner_id: str) -> bool:
        """Delete an item."""
        db = mongodb_checkpoint.db
        result = await db.items.delete_one({
            "_id": ObjectId(item_id),
            "owner_id": owner_id
        })
        return result.deleted_count > 0
    
    async def search_items(
        self,
        query: str,
        field: str = "all",
        limit: int = 20,
        offset: int = 0
    ) -> List[Item]:
        """Search items by text query.
        
        Args:
            query: Search text
            field: Field to search (all, name, description, data)
            limit: Maximum results
            offset: Skip results
        """
        db = mongodb_checkpoint.db
        
        # Build search filter
        regex_query = {"$regex": query, "$options": "i"}
        
        if field == "name":
            search_filter = {"name": regex_query}
        elif field == "description":
            search_filter = {"description": regex_query}
        elif field == "data":
            # Search in JSON data (convert to string for regex)
            search_filter = {"$where": f"JSON.stringify(this.data).match(/{query}/i)"}
        else:  # all
            search_filter = {
                "$or": [
                    {"name": regex_query},
                    {"description": regex_query}
                ]
            }
        
        cursor = db.items.find(search_filter).skip(offset).limit(limit)
        items = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            items.append(Item(**doc))
        return items
    
    async def get_statistics(self, user_id: str) -> dict:
        """Get statistics about items.
        
        Args:
            user_id: Current user ID for personalized stats
        """
        db = mongodb_checkpoint.db
        
        # Total count
        total_count = await db.items.count_documents({})
        
        # User's items count
        user_count = await db.items.count_documents({"owner_id": user_id})
        
        # Recent items (last 7 days)
        from datetime import timedelta
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_count = await db.items.count_documents({
            "created_at": {"$gte": seven_days_ago}
        })
        
        # Most recent item
        latest = await db.items.find_one(
            {},
            sort=[("created_at", -1)]
        )
        
        return {
            "total_items": total_count,
            "user_items": user_count,
            "recent_items_7d": recent_count,
            "latest_item": {
                "id": str(latest["_id"]) if latest else None,
                "name": latest.get("name") if latest else None,
                "created_at": latest.get("created_at").isoformat() if latest and latest.get("created_at") else None
            } if latest else None
        }
    
    async def bulk_create(self, items: List[ItemCreate], owner_id: str) -> List[Item]:
        """Create multiple items at once.
        
        Args:
            items: List of items to create
            owner_id: Owner user ID
        """
        db = mongodb_checkpoint.db
        
        if not items:
            return []
        
        now = datetime.now(timezone.utc)
        item_dicts = []
        for item_data in items:
            item_dicts.append({
                "name": item_data.name,
                "description": item_data.description,
                "data": item_data.data,
                "owner_id": owner_id,
                "created_at": now,
                "updated_at": now
            })
        
        result = await db.items.insert_many(item_dicts)
        
        # Fetch created items
        created_items = []
        for i, inserted_id in enumerate(result.inserted_ids):
            item_dicts[i]["id"] = str(inserted_id)
            created_items.append(Item(**item_dicts[i]))
        
        return created_items
    
    async def bulk_delete(self, item_ids: List[str], owner_id: str) -> int:
        """Delete multiple items at once.
        
        Args:
            item_ids: List of item IDs to delete
            owner_id: Owner user ID (for authorization)
            
        Returns:
            Number of items deleted
        """
        db = mongodb_checkpoint.db
        
        if not item_ids:
            return 0
        
        # Convert to ObjectIds
        object_ids = []
        for item_id in item_ids:
            try:
                object_ids.append(ObjectId(item_id))
            except Exception:
                continue  # Skip invalid IDs
        
        if not object_ids:
            return 0
        
        result = await db.items.delete_many({
            "_id": {"$in": object_ids},
            "owner_id": owner_id
        })
        
        return result.deleted_count


# Global instances
user_crud = UserCRUD()
item_crud = ItemCRUD()
