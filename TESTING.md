# AI Experiments - End-to-End Testing Guide

## Prerequisites

Make sure all services are running:

```bash
# Check backend
curl http://localhost:8000/health
# Expected: {"status":"healthy","mongodb":"connected","redis":"connected"}

# Check frontend
curl http://localhost:3000 -o /dev/null -w "%{http_code}"
# Expected: 200
```

If not running:
```bash
# Start backend (Docker)
cd /Users/nik/workspace/google-copilot/AI-Experiments
docker-compose up -d

# Start frontend
cd frontend
npm run dev
```

---

## Test 1: User Registration & Login

### Via UI (http://localhost:3000)
1. Open http://localhost:3000
2. Click "Don't have an account? Register"
3. Fill in:
   - Username: `demouser`
   - Email: `demo@example.com`
   - Password: `demo123456`
4. Click "Register"
5. You should be logged in automatically

### Via CLI
```bash
# Register a new user
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "cliuser", "password": "clipass123", "email": "cli@test.com", "role": "user"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "cliuser", "password": "clipass123"}'

# Save the access_token from response for next steps
export TOKEN="<paste_access_token_here>"
```

---

## Test 2: Items CRUD Operations

### Via UI
1. Login at http://localhost:3000
2. Click "Items CRUD" tab
3. Click "➕ New Item"
4. Fill in:
   - Name: `Test Item`
   - Description: `My first item`
   - Data (JSON): `{"key": "value", "count": 42}`
5. Click "✅ Create"
6. You should see the item in the list
7. Try "✏️ Edit" and "🗑️ Delete" buttons

### Via CLI
```bash
# Create an item
curl -X POST http://localhost:8000/items \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "CLI Item", "description": "Created via CLI", "data": {"test": true}}'

# List all items
curl http://localhost:8000/items \
  -H "Authorization: Bearer $TOKEN"

# Get specific item (use id from list response)
curl http://localhost:8000/items/<item_id> \
  -H "Authorization: Bearer $TOKEN"

# Update item
curl -X PUT http://localhost:8000/items/<item_id> \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "Updated Item", "description": "Modified", "data": {"updated": true}}'

# Delete item
curl -X DELETE http://localhost:8000/items/<item_id> \
  -H "Authorization: Bearer $TOKEN"
```

---

## Test 3: MCP Server Tools

### Via UI
1. Login at http://localhost:3000
2. Click "MCP Server" tab
3. You should see available tools on the left panel
4. Click on a tool (e.g., "create_item")
5. Fill in the parameters
6. Click "▶️ Execute Tool"
7. See result on the right panel

### Via CLI
```bash
# Get MCP capabilities
curl http://localhost:8000/mcp/capabilities

# Get available tools (filtered by your role)
curl http://localhost:8000/stream/mcp/tools \
  -H "Authorization: Bearer $TOKEN"

# Call create_item tool
curl -X POST http://localhost:8000/stream/mcp/call/create_item \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "MCP Item", "description": "Created via MCP"}'

# Call read_item tool
curl -X POST http://localhost:8000/stream/mcp/call/read_item \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"item_id": "<item_id>"}'
```

---

## Test 4: Multi-Agent with Plan Mode (SSE Streaming)

### Via UI
1. Login at http://localhost:3000
2. Click "AI Agent" tab
3. In the goal input, type:
   ```
   Search for user data, analyze the results, and create a summary report
   ```
4. Click "🚀 Create Plan"
5. Watch the Event Stream panel - you'll see SSE events arriving in real-time
6. Once plan is complete, you can edit the steps
7. Click "💾 Save Changes" if you modified anything
8. Click "▶️ Execute Plan"
9. Watch parallel and sequential tasks execute in the Event Stream

### Via CLI
```bash
# Create a session
curl -X POST http://localhost:8000/stream/sessions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"goal": "Search for data and create a report"}'

# Save session_id from response
export SESSION_ID="<session_id>"

# Stream plan generation (SSE)
curl -N http://localhost:8000/stream/sessions/$SESSION_ID/plan \
  -H "Authorization: Bearer $TOKEN"

# Get session state
curl http://localhost:8000/stream/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN"

# Update plan (modify step descriptions)
curl -X PUT http://localhost:8000/stream/sessions/$SESSION_ID/plan \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"session_id": "'$SESSION_ID'", "plan": [...]}'

# Stream plan execution (SSE)
curl -N http://localhost:8000/stream/sessions/$SESSION_ID/execute \
  -H "Authorization: Bearer $TOKEN"
```

---

## Test 5: RBAC (Role-Based Access Control)

### Create users with different roles
```bash
# Admin user
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "adminuser", "password": "admin123", "email": "admin@test.com", "role": "admin"}'

# Read-only user
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "readonly", "password": "readonly123", "email": "ro@test.com", "role": "read_only"}'
```

### Test permission differences
```bash
# Login as read_only user
READONLY_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "readonly", "password": "readonly123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Try to create item (should fail - no write permission)
curl -X POST http://localhost:8000/items \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $READONLY_TOKEN" \
  -d '{"name": "Test", "description": "Should fail"}'

# List items (should work - read permission)
curl http://localhost:8000/items \
  -H "Authorization: Bearer $READONLY_TOKEN"

# Check available MCP tools (should be limited)
curl http://localhost:8000/stream/mcp/tools \
  -H "Authorization: Bearer $READONLY_TOKEN"
```

---

## Test 6: Token Generation for MCP RBAC

```bash
# Generate a scoped token
curl -X POST http://localhost:8000/auth/token/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"user_id": "mcp-client-1", "permissions": ["items:read", "mcp:read"], "expires_hours": 24}'

# Validate token
curl -X POST http://localhost:8000/auth/token/validate \
  -H "Content-Type: application/json" \
  -d '{"token": "<generated_token>"}'
```

---

## Test 7: Checkpoint Storage (Hot/Cold)

```bash
# Create session (stored in MongoDB - hot storage)
SESSION=$(curl -s -X POST http://localhost:8000/stream/sessions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"goal": "Test checkpoint storage"}')
SESSION_ID=$(echo $SESSION | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")

# Archive to Redis (cold storage)
curl -X POST http://localhost:8000/agent/sessions/$SESSION_ID/archive \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"ttl_days": 7}'
```

---

## Troubleshooting

### No tools showing in MCP panel
- Make sure you're logged in
- Check browser console for errors
- Verify backend is running: `curl http://localhost:8000/health`

### Items not loading
- Check if you have created any items first
- Try creating one via CLI to test

### SSE events not streaming
- Check browser Network tab for SSE connections
- Make sure you have a valid session created first

### Login fails
- Try registering a new user
- Check backend logs: `docker logs ai-experiments-app-1`

---

## Quick Full Test Script

```bash
#!/bin/bash
set -e

echo "=== 1. Health Check ==="
curl -s http://localhost:8000/health | python3 -m json.tool

echo -e "\n=== 2. Register User ==="
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "fulltest", "password": "fulltest123", "email": "full@test.com"}' | python3 -m json.tool || echo "User may already exist"

echo -e "\n=== 3. Login ==="
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "fulltest", "password": "fulltest123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
echo "Token obtained: ${TOKEN:0:20}..."

echo -e "\n=== 4. Create Item ==="
ITEM=$(curl -s -X POST http://localhost:8000/items \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "Test Item", "description": "E2E test", "data": {"test": true}}')
echo $ITEM | python3 -m json.tool
ITEM_ID=$(echo $ITEM | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

echo -e "\n=== 5. List Items ==="
curl -s http://localhost:8000/items -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 6. MCP Tools ==="
curl -s http://localhost:8000/stream/mcp/tools -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 7. Create Agent Session ==="
SESSION=$(curl -s -X POST http://localhost:8000/stream/sessions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"goal": "Search and analyze data"}')
echo $SESSION | python3 -m json.tool
SESSION_ID=$(echo $SESSION | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")

echo -e "\n=== 8. Stream Plan (5 seconds) ==="
timeout 5 curl -s -N http://localhost:8000/stream/sessions/$SESSION_ID/plan \
  -H "Authorization: Bearer $TOKEN" || true

echo -e "\n\n=== ✅ All tests completed! ==="
```

Save as `test-e2e.sh` and run: `chmod +x test-e2e.sh && ./test-e2e.sh`
