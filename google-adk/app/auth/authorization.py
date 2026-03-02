"""Authorization and authentication utilities."""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings
from app.models import TokenData, UserRole

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


# Role-based permissions mapping
ROLE_PERMISSIONS: Dict[UserRole, List[str]] = {
    UserRole.ADMIN: [
        "users:read", "users:write", "users:delete",
        "items:read", "items:write", "items:delete",
        "agent:execute", "agent:admin",
        "mcp:read", "mcp:write", "mcp:admin",
    ],
    UserRole.USER: [
        "items:read", "items:write", "items:delete",
        "agent:execute",
        "mcp:read", "mcp:write",
    ],
    UserRole.READ_ONLY: [
        "items:read",
        "mcp:read",
    ],
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(
    user_id: str,
    username: str,
    role: UserRole,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    permissions = ROLE_PERMISSIONS.get(role, [])

    to_encode: Dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "role": role.value,
        "permissions": permissions,
    }

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)

    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> TokenData:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role: str = payload.get("role")
        permissions: List[str] = payload.get("permissions", [])

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return TokenData(
            user_id=user_id,
            username=username,
            role=UserRole(role) if role else None,
            permissions=permissions,
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Redis client for token blacklist (imported lazily to avoid circular imports)
_redis_client = None


async def _get_redis():
    """Get Redis client for token blacklist checks."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis
        _redis_client = redis.from_url(
            settings.redis_url,
            db=settings.redis_db,
            decode_responses=True,
        )
    return _redis_client


async def is_token_blacklisted(token: str) -> bool:
    """Check if a token has been blacklisted."""
    try:
        r = await _get_redis()
        return await r.exists(f"blacklist:{token}") > 0
    except Exception:
        return False


async def blacklist_token(token: str, ttl_seconds: int = 3600) -> None:
    """Add a token to the blacklist."""
    try:
        r = await _get_redis()
        await r.setex(f"blacklist:{token}", ttl_seconds, "1")
    except Exception:
        pass


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """Get current authenticated user from token."""
    token = credentials.credentials

    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_token(token)


def require_permission(permission: str):
    """Dependency to require a specific permission."""
    async def permission_checker(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        if permission not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires '{permission}'",
            )
        return current_user

    return permission_checker


class AuthorizationTool:
    """Authorization tool for generating and managing user tokens."""

    @staticmethod
    async def generate_user_token(
        user_id: str,
        username: str,
        role: UserRole,
        expires_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate a new token for a user."""
        expires_delta = timedelta(minutes=expires_minutes) if expires_minutes else None

        token = create_access_token(
            user_id=user_id,
            username=username,
            role=role,
            expires_delta=expires_delta,
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_minutes or settings.jwt_access_token_expire_minutes,
            "permissions": ROLE_PERMISSIONS.get(role, []),
        }

    @staticmethod
    async def revoke_token(token: str, ttl_seconds: int = 3600) -> bool:
        """Revoke a token by adding it to the blacklist."""
        await blacklist_token(token, ttl_seconds)
        return True

    @staticmethod
    def validate_token(token: str) -> TokenData:
        """Validate a token and return its data."""
        return decode_token(token)

    @staticmethod
    def get_permissions_for_role(role: UserRole) -> List[str]:
        """Get all permissions for a specific role."""
        return ROLE_PERMISSIONS.get(role, [])


# Global instance
authorization_tool = AuthorizationTool()
