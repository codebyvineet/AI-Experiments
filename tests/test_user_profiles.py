"""Tests for the user profiles module."""

import pytest
from user_profiles import UserProfile, UserProfileStore


def test_create_profile():
    store = UserProfileStore()
    profile = store.create(name="Alice", email="alice@example.com", bio="AI researcher")
    assert profile.name == "Alice"
    assert profile.email == "alice@example.com"
    assert profile.bio == "AI researcher"
    assert profile.id is not None


def test_get_profile():
    store = UserProfileStore()
    created = store.create(name="Bob", email="bob@example.com")
    retrieved = store.get(created.id)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.name == "Bob"


def test_get_nonexistent_profile():
    store = UserProfileStore()
    assert store.get("nonexistent-id") is None


def test_list_profiles():
    store = UserProfileStore()
    store.create(name="Alice", email="alice@example.com")
    store.create(name="Bob", email="bob@example.com")
    profiles = store.list()
    assert len(profiles) == 2


def test_update_profile():
    store = UserProfileStore()
    profile = store.create(name="Carol", email="carol@example.com")
    updated = store.update(profile.id, name="Caroline", bio="Updated bio")
    assert updated is not None
    assert updated.name == "Caroline"
    assert updated.bio == "Updated bio"
    assert updated.email == "carol@example.com"


def test_update_clear_bio():
    store = UserProfileStore()
    profile = store.create(name="Dave", email="dave@example.com", bio="Some bio")
    updated = store.update(profile.id, bio=None)
    assert updated is not None
    assert updated.bio is None


def test_update_nonexistent_profile():
    store = UserProfileStore()
    assert store.update("nonexistent-id", name="Nobody") is None


def test_delete_profile():
    store = UserProfileStore()
    profile = store.create(name="Eve", email="eve@example.com")
    assert store.delete(profile.id) is True
    assert store.get(profile.id) is None


def test_delete_nonexistent_profile():
    store = UserProfileStore()
    assert store.delete("nonexistent-id") is False


def test_profile_to_dict():
    profile = UserProfile(name="Frank", email="frank@example.com", bio="Engineer")
    d = profile.to_dict()
    assert d["name"] == "Frank"
    assert d["email"] == "frank@example.com"
    assert d["bio"] == "Engineer"
    assert "id" in d


def test_create_invalid_email():
    store = UserProfileStore()
    with pytest.raises(ValueError, match="Invalid email address"):
        store.create(name="Bad", email="not-an-email")


def test_update_invalid_email():
    store = UserProfileStore()
    profile = store.create(name="Grace", email="grace@example.com")
    with pytest.raises(ValueError, match="Invalid email address"):
        store.update(profile.id, email="bad-email")
