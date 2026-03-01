"""User profiles module for AI-Experiments application."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UNSET = object()


def _validate_email(email: str) -> None:
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email!r}")


@dataclass
class UserProfile:
    """Represents a user profile in the application."""

    name: str
    email: str
    bio: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """Serialize the profile to a dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "bio": self.bio,
        }


class UserProfileStore:
    """In-memory store for user profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, UserProfile] = {}

    def create(self, name: str, email: str, bio: Optional[str] = None) -> UserProfile:
        """Create and store a new user profile."""
        _validate_email(email)
        profile = UserProfile(name=name, email=email, bio=bio)
        self._profiles[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> Optional[UserProfile]:
        """Retrieve a user profile by ID."""
        return self._profiles.get(profile_id)

    def list(self) -> list[UserProfile]:
        """Return all stored user profiles."""
        return list(self._profiles.values())

    def update(
        self,
        profile_id: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        bio: object = _UNSET,
    ) -> Optional[UserProfile]:
        """Update an existing user profile. Returns None if not found.

        Pass ``bio=None`` to explicitly clear the bio field.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            return None
        if name is not None:
            profile.name = name
        if email is not None:
            _validate_email(email)
            profile.email = email
        if bio is not _UNSET:
            profile.bio = bio  # type: ignore[assignment]
        return profile

    def delete(self, profile_id: str) -> bool:
        """Delete a user profile by ID. Returns True if deleted, False if not found."""
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            return True
        return False
