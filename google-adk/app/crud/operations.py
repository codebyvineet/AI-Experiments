"""MongoDB database connection and CRUD operations."""

from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings
from app.models import User, UserCreate, Item, ItemCreate, ItemUpdate
from app.auth import get_password_hash

settings = get_settings()

# Shared async MongoDB client
_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def connect_db() -> None:
    """Connect to MongoDB and create indexes."""
    global _client, _db
    _client = AsyncIOMotorClient(settings.mongodb_url)
    _db = _client[settings.mongodb_database]

    # Create indexes
    await _db.users.create_index("username", unique=True)
    await _db.users.create_index("email", unique=True)
    await _db.items.create_index("owner_id")
    await _db.agent_sessions.create_index("session_id", unique=True)
    await _db.agent_sessions.create_index("user_id")


async def disconnect_db() -> None:
    """Disconnect from MongoDB."""
    global _client
    if _client:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the current database handle."""
    if _db is None:
        raise RuntimeError("Database not connected — call connect_db() first.")
    return _db


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

class UserCRUD:
    """CRUD operations for users."""

    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user."""
        db = get_db()

        existing = await db.users.find_one({
            "$or": [
                {"username": user_data.username},
                {"email": user_data.email},
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
            "updated_at": datetime.now(timezone.utc),
        }

        result = await db.users.insert_one(user_dict)
        user_dict["id"] = str(result.inserted_id)
        user_dict.pop("_id", None)
        return User(**user_dict)

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        db = get_db()
        doc = await db.users.find_one({"_id": ObjectId(user_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return User(**doc)
        return None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        db = get_db()
        doc = await db.users.find_one({"username": username})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return User(**doc)
        return None

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List all users."""
        db = get_db()
        cursor = db.users.find().skip(skip).limit(limit)
        users = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            users.append(User(**doc))
        return users


# ---------------------------------------------------------------------------
# Item CRUD
# ---------------------------------------------------------------------------

class ItemCRUD:
    """CRUD operations for items."""

    async def create_item(self, item_data: ItemCreate, owner_id: str) -> Item:
        """Create a new item."""
        db = get_db()

        item_dict = {
            "name": item_data.name,
            "description": item_data.description,
            "data": item_data.data,
            "owner_id": owner_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        result = await db.items.insert_one(item_dict)
        item_dict["id"] = str(result.inserted_id)
        return Item(**item_dict)

    async def get_item(self, item_id: str) -> Optional[Item]:
        """Get item by ID."""
        db = get_db()
        doc = await db.items.find_one({"_id": ObjectId(item_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return Item(**doc)
        return None

    async def list_items(
        self,
        owner_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Item]:
        """List items, optionally filtered by owner."""
        db = get_db()
        query = {"owner_id": owner_id} if owner_id else {}
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
        owner_id: str,
    ) -> Optional[Item]:
        """Update an item (only owner can update)."""
        db = get_db()

        existing = await db.items.find_one({
            "_id": ObjectId(item_id),
            "owner_id": owner_id,
        })
        if not existing:
            return None

        updates = item_data.model_dump(exclude_none=True)
        updates["updated_at"] = datetime.now(timezone.utc)

        await db.items.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": updates},
        )
        return await self.get_item(item_id)

    async def delete_item(self, item_id: str, owner_id: str) -> bool:
        """Delete an item (only owner can delete)."""
        db = get_db()
        result = await db.items.delete_one({
            "_id": ObjectId(item_id),
            "owner_id": owner_id,
        })
        return result.deleted_count > 0


# Global instances
user_crud = UserCRUD()
item_crud = ItemCRUD()
