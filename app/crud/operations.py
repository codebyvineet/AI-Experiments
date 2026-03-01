"""CRUD operations for users and items."""

from typing import Optional, List
from datetime import datetime
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
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await db.users.insert_one(user_dict)
        user_dict["id"] = str(result.inserted_id)
        del user_dict["_id"] if "_id" in user_dict else None
        
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
        updates["updated_at"] = datetime.utcnow()
        
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
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
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
        updates["updated_at"] = datetime.utcnow()
        
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


# Global instances
user_crud = UserCRUD()
item_crud = ItemCRUD()
