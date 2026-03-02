#!/bin/bash
# Create demo users for RBAC testing
# This script creates 3 users with different permission levels

API_URL="${API_URL:-http://localhost:8000}"

echo "=== Creating RBAC Demo Users ==="
echo "API URL: $API_URL"
echo ""

# Admin user - full access
echo "1. Creating admin_demo (admin role)..."
curl -s -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin_demo",
    "email": "admin@demo.com",
    "password": "admin123",
    "role": "admin"
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   ✅ Created: {d.get(\"username\", \"error\")} (role: {d.get(\"role\", d.get(\"detail\", \"unknown\"))})')" 2>/dev/null || echo "   ❌ Failed"

# Normal user - can CRUD items, execute agent
echo "2. Creating user_demo (user role)..."
curl -s -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "user_demo",
    "email": "user@demo.com",
    "password": "user123",
    "role": "user"
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   ✅ Created: {d.get(\"username\", \"error\")} (role: {d.get(\"role\", d.get(\"detail\", \"unknown\"))})')" 2>/dev/null || echo "   ❌ Failed"

# Viewer user - read only
echo "3. Creating viewer_demo (read_only role)..."
curl -s -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "viewer_demo",
    "email": "viewer@demo.com",
    "password": "viewer123",
    "role": "read_only"
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   ✅ Created: {d.get(\"username\", \"error\")} (role: {d.get(\"role\", d.get(\"detail\", \"unknown\"))})')" 2>/dev/null || echo "   ❌ Failed"

echo ""
echo "=== Demo Users Created ==="
echo ""
echo "Login credentials:"
echo "  admin_demo / admin123  - Full access (admin)"
echo "  user_demo  / user123   - Can CRUD items, execute agent"
echo "  viewer_demo / viewer123 - Read-only access"
echo ""
echo "=== Testing RBAC ==="
echo ""

# Test with viewer_demo - should fail on write
echo "Testing viewer_demo (read_only) - should FAIL on create item..."
TOKEN=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "viewer_demo", "password": "viewer123"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -n "$TOKEN" ]; then
  RESULT=$(curl -s -X POST "$API_URL/items/" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"name": "Test Item", "description": "Should fail"}')
  
  if echo "$RESULT" | grep -q "403\|Forbidden\|permission\|Permission denied"; then
    echo "   ✅ Correctly denied - viewer cannot create items"
  else
    echo "   ❌ Unexpected: $RESULT"
  fi
  
  # Test read - should succeed
  echo "Testing viewer_demo - should SUCCEED on list items..."
  RESULT=$(curl -s -X GET "$API_URL/items/" -H "Authorization: Bearer $TOKEN")
  if echo "$RESULT" | grep -q "id\|name\|\[\]"; then
    echo "   ✅ Read access works"
  else
    echo "   ❌ Unexpected: $RESULT"
  fi
else
  echo "   ❌ Failed to login as viewer_demo"
fi

echo ""
echo "=== RBAC Demo Ready ==="
echo "Open http://localhost:3000 and login with each user to test permissions."
