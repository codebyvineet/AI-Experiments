# AI-Experiments

A collection of AI experiments and utilities.

## User Profiles

The `user_profiles.py` module provides a simple in-memory user profile store with full CRUD support.

### Usage

```python
from user_profiles import UserProfileStore

store = UserProfileStore()

# Create
profile = store.create(name="Alice", email="alice@example.com", bio="AI researcher")

# Read
retrieved = store.get(profile.id)

# Update
store.update(profile.id, bio="Senior AI researcher")

# List all
all_profiles = store.list()

# Delete
store.delete(profile.id)
```

### Running Tests

```bash
python -m pytest tests/
```