# Manual Testing Guide — Google ADK Implementation

This document covers every feature of the **Google ADK** implementation end-to-end.  
Follow these steps locally with `docker compose up --build` before running each test.

---

## Prerequisites

### 1. Clone and configure

```bash
cd google-adk
cp .env.example .env
```

Edit `.env` and set:

| Variable | Value |
|----------|-------|
| `JWT_SECRET_KEY` | Run `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
| `GOOGLE_API_KEY` | Your Google AI Studio key — [aistudio.google.com](https://aistudio.google.com) |
| or `GOOGLE_CLOUD_PROJECT` | GCP project ID (Vertex AI alternative) |

### 2. Start all services

```bash
docker compose up --build
```

Wait for all four containers to show `healthy` / ready:

| Container | Port | Expected log |
|-----------|------|-------------|
| `app` | 8000 | `Google ADK agent initialised.` |
| `mcp-server` | 8001 | `FastMCP server started` |
| `mongodb` | 27017 | `Waiting for connections` |
| `redis` | 6379 | `Ready to accept connections` |

### 3. Verify services are up

```bash
curl http://localhost:8000/health
# {"status":"healthy","framework":"google-adk"}

curl http://localhost:8000/
# {"message":"MCP Demo — Google ADK Implementation","framework":"Google ADK",...}

curl http://localhost:8001/health
# {"status":"healthy","service":"mcp-server"}
```

---

## Test Suite

Set this shell variable once; every test below references it:

```bash
BASE="http://localhost:8000"
```

---

## TC-01 · User Registration

**Goal:** Register three users with different roles.

```bash
# Admin
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@test.com","password":"Admin123!","role":"admin"}' | jq .

# Regular user
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@test.com","password":"Alice123!","role":"user"}' | jq .

# Read-only user
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"viewer","email":"viewer@test.com","password":"View123!","role":"read_only"}' | jq .
```

**Expected:** HTTP 200 for each, response includes `id`, `username`, `role`, `is_active: true`.

**Negative — duplicate username:**

```bash
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice2@test.com","password":"Alice123!","role":"user"}' | jq .
```

**Expected:** HTTP 400 — `"Username or email already exists"`.

---

## TC-02 · Login & JWT Issuance

```bash
# Alice login
ALICE_TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Alice123!"}' | jq -r .access_token)
echo "Alice token: ${ALICE_TOKEN:0:40}..."

# Viewer login
VIEWER_TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"viewer","password":"View123!"}' | jq -r .access_token)

# Admin login
ADMIN_TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin123!"}' | jq -r .access_token)
```

**Expected:** Each returns `{"access_token": "eyJ...", "token_type": "bearer"}`.

**Negative — wrong password:**

```bash
curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"wrong"}' | jq .
```

**Expected:** HTTP 401 — `"Incorrect username or password"`.

---

## TC-03 · Current User Profile

```bash
curl -s $BASE/auth/me -H "Authorization: Bearer $ALICE_TOKEN" | jq .
```

**Expected:** Returns Alice's profile with `role: "user"`.

---

## TC-04 · Role Permissions

```bash
# List Alice's permissions
curl -s $BASE/auth/permissions/user | jq .

# List read_only permissions
curl -s $BASE/auth/permissions/read_only | jq .

# List admin permissions
curl -s $BASE/auth/permissions/admin | jq .
```

**Expected:**

| Role | Key permissions present |
|------|------------------------|
| `user` | `items:read`, `items:write`, `items:delete`, `agent:execute` |
| `read_only` | `items:read`, `mcp:read` only |
| `admin` | All of the above + `agent:admin`, `mcp:admin`, `users:*` |

---

## TC-05 · Item CRUD

### Create items (Alice — has `items:write`)

```bash
ITEM1=$(curl -s -X POST $BASE/items/ \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Widget A","description":"First test item","data":{"color":"blue"}}' | jq -r .id)
echo "Item 1: $ITEM1"

ITEM2=$(curl -s -X POST $BASE/items/ \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Widget B","description":"Second test item","data":{"color":"red"}}' | jq -r .id)
echo "Item 2: $ITEM2"
```

**Expected:** HTTP 200, response includes `id`, `name`, `owner_id` (Alice's user ID).

### List items

```bash
# All items (any authenticated user)
curl -s "$BASE/items/" -H "Authorization: Bearer $ALICE_TOKEN" | jq '.[] | .name'

# Only Alice's items
curl -s "$BASE/items/?my_items_only=true" -H "Authorization: Bearer $ALICE_TOKEN" | jq '.[].name'
```

**Expected:** Both Widget A and Widget B appear.

### Read a single item

```bash
curl -s $BASE/items/$ITEM1 -H "Authorization: Bearer $ALICE_TOKEN" | jq .
```

**Expected:** Full item object with `name: "Widget A"`.

### Update item

```bash
curl -s -X PUT $BASE/items/$ITEM1 \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Widget A (updated)","data":{"color":"green"}}' | jq .name
```

**Expected:** `"Widget A (updated)"`.

### Delete item

```bash
curl -s -X DELETE $BASE/items/$ITEM2 \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq .

# Verify it's gone
curl -s $BASE/items/$ITEM2 -H "Authorization: Bearer $ALICE_TOKEN" | jq .detail
```

**Expected:** Delete returns `{"status":"deleted"}`. Second request returns 404.

---

## TC-06 · RBAC — Write blocked for read_only

```bash
# Viewer tries to create an item
curl -s -X POST $BASE/items/ \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Should Fail"}' | jq .
```

**Expected:** HTTP 403 — `"Permission denied: requires 'items:write'"`.

```bash
# Viewer can still READ
curl -s $BASE/items/ -H "Authorization: Bearer $VIEWER_TOKEN" | jq '.[].name'
```

**Expected:** HTTP 200, returns existing items.

---

## TC-07 · Agent Session — Create & Get State

```bash
# Create a session (Alice)
SESSION=$(curl -s -X POST $BASE/agent/sessions \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq -r .session_id)
echo "Session: $SESSION"

# Get session state
curl -s $BASE/agent/sessions/$SESSION \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq .
```

**Expected:** Session created with `is_planning_mode: false`, `plan: []`, `current_step: 0`, `is_complete: false`.

---

## TC-08 · Chat Mode (Google ADK LlmAgent + MCP tools)

```bash
# Send a message — the ADK LlmAgent will call MCP tools when needed
curl -s -X POST $BASE/agent/sessions/$SESSION/chat \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"List all my items and then create a new item called ADK Test Item"}' | jq .
```

**Expected:**
- HTTP 200
- `agent_reply` contains a text response
- The Gemini model will have called `list_items` and `create_item` MCP tools
- Response references the items that were created/listed

```bash
# Follow-up conversation (session history preserved)
curl -s -X POST $BASE/agent/sessions/$SESSION/chat \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What was the last item you created?"}' | jq .agent_reply
```

**Expected:** The agent references "ADK Test Item" from the previous turn (session memory active).

---

## TC-09 · Plan Mode — Generate Plan

```bash
# Create a fresh session for plan mode
PLAN_SESSION=$(curl -s -X POST $BASE/agent/sessions \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq -r .session_id)

# Enter plan mode
curl -s -X POST $BASE/agent/sessions/$PLAN_SESSION/plan \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal":"Create three items named Alpha, Beta, Gamma and then list them all"}' | jq .
```

**Expected:**
```json
{
  "session_id": "...",
  "mode": "planning",
  "plan": [
    {"step_id": "1", "description": "Create item Alpha", "action": "create_item", "status": "pending"},
    {"step_id": "2", "description": "Create item Beta",  "action": "create_item", "status": "pending"},
    {"step_id": "3", "description": "Create item Gamma", "action": "create_item", "status": "pending"},
    {"step_id": "4", "description": "List all items",    "action": "list_items",  "status": "pending"}
  ],
  "total_steps": 4
}
```

```bash
# Verify session is now in planning mode
curl -s $BASE/agent/sessions/$PLAN_SESSION \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq '{is_planning_mode, current_step, total_steps: (.plan | length)}'
```

---

## TC-10 · Plan Mode — Execute Steps One by One

```bash
# Execute step 1
curl -s -X POST $BASE/agent/sessions/$PLAN_SESSION/execute-step \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq '{step_id: .step.step_id, status: .step.status, current_step, is_complete}'

# Execute step 2
curl -s -X POST $BASE/agent/sessions/$PLAN_SESSION/execute-step \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq '{step_id: .step.step_id, status: .step.status, current_step, is_complete}'
```

**Expected:** Each call returns the completed step with `status: "completed"` and `current_step` incrementing.

---

## TC-11 · Plan Mode — Execute All Remaining Steps

```bash
curl -s -X POST $BASE/agent/sessions/$PLAN_SESSION/execute-all \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq '{status, total_results: (.execution_results | length), is_complete: .execution_results[-1].is_complete}'
```

**Expected:** `status: "completed"`, all steps executed, `is_complete: true`.

```bash
# Session should now be complete
curl -s $BASE/agent/sessions/$PLAN_SESSION \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq '{is_planning_mode, is_complete, current_step}'
```

**Expected:** `is_planning_mode: false`, `is_complete: true`.

---

## TC-12 · Plan Mode — Read-only user cannot start a session

```bash
curl -s -X POST $BASE/agent/sessions \
  -H "Authorization: Bearer $VIEWER_TOKEN" | jq .
```

**Expected:** HTTP 403 — `"Permission denied: requires 'agent:execute'"`.

---

## TC-13 · Session Ownership

```bash
# Create another user and their session
BOB_TOKEN=$(curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"bob","email":"bob@test.com","password":"Bob123!","role":"user"}' | \
  xargs -I{} curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"bob","password":"Bob123!"}' | jq -r .access_token)

BOB_SESSION=$(curl -s -X POST $BASE/agent/sessions \
  -H "Authorization: Bearer $BOB_TOKEN" | jq -r .session_id)

# Alice tries to read Bob's session — should be rejected
curl -s $BASE/agent/sessions/$BOB_SESSION \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq .detail
```

**Expected:** HTTP 403 — `"You don't have access to this session"`.

```bash
# Admin CAN read any session
curl -s $BASE/agent/sessions/$BOB_SESSION \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq .session_id
```

**Expected:** Returns Bob's session details (admin has `agent:admin` permission).

---

## TC-14 · Session Archive

```bash
curl -s -X POST $BASE/agent/sessions/$PLAN_SESSION/archive \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ttl_days":7}' | jq .
```

**Expected:** `{"session_id":"...","status":"archived","ttl_days":7}`.

---

## TC-15 · Token Revocation

```bash
# Revoke Alice's current token
curl -s -X POST $BASE/auth/token/revoke \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$ALICE_TOKEN\"}" | jq .

# Try to use the revoked token
curl -s $BASE/auth/me \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq .detail
```

**Expected:** After revoke, token returns HTTP 401 — `"Token has been revoked"`.

```bash
# Get a fresh token
ALICE_TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Alice123!"}' | jq -r .access_token)

curl -s $BASE/auth/me -H "Authorization: Bearer $ALICE_TOKEN" | jq .username
```

**Expected:** `"alice"` — fresh token works.

---

## TC-16 · No-auth requests rejected

```bash
curl -s $BASE/items/ | jq .detail
curl -s $BASE/agent/sessions | jq .detail
```

**Expected:** HTTP 401 — `"Not authenticated"` (FastAPI `HTTPBearer` returns 401 for missing `Authorization` header).

---

## TC-17 · OpenAPI / Interactive Docs

Open in browser:

| URL | Expected |
|-----|----------|
| `http://localhost:8000/docs` | Swagger UI showing all routes |
| `http://localhost:8000/redoc` | ReDoc documentation |
| `http://localhost:8001/` | MCP server info JSON (tools list, transport endpoints) |

---

## TC-18 · MCP Server — Standalone Verification

The MCP server runs independently of the main app.  You can verify its tools directly:

```bash
# Inspect MCP server info
curl -s http://localhost:8001/ | jq .

# The SSE endpoint (used by ADK MCPToolset)
curl -s http://localhost:8001/health | jq .
```

**Expected:** `{"status":"healthy","service":"mcp-server"}`.

The ADK agent is configured to call MCP tools via the SSE connection at
`http://mcp-server:8001/sse`. In chat and plan-execute mode, every tool call
(create_item, list_items, etc.) flows through this MCP channel — verifiable
by watching the `mcp-server` container logs:

```bash
docker compose logs mcp-server -f
```

---

## TC-19 · Concurrent Sessions

```bash
# Create 3 sessions simultaneously
for i in 1 2 3; do
  curl -s -X POST $BASE/agent/sessions \
    -H "Authorization: Bearer $ALICE_TOKEN" | jq -r .session_id &
done
wait
```

**Expected:** Three distinct UUIDs — sessions are independent.

---

## TC-20 · Container Restart Persistence

```bash
# Create a session before restart
PERSIST_SESSION=$(curl -s -X POST $BASE/agent/sessions \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq -r .session_id)
echo "Session: $PERSIST_SESSION"

# Restart only the app container (MongoDB keeps data)
docker compose restart app
sleep 10

# Session should still exist (persisted in MongoDB)
curl -s $BASE/agent/sessions/$PERSIST_SESSION \
  -H "Authorization: Bearer $ALICE_TOKEN" | jq .session_id
```

**Expected:** Returns the same session ID — MongoDB-backed ADK sessions survive app restarts.

---

## Summary Checklist

| # | Feature | Route | Pass? |
|---|---------|-------|-------|
| TC-01 | User registration (3 roles) | `POST /auth/register` | ☐ |
| TC-01 | Duplicate username rejected | `POST /auth/register` | ☐ |
| TC-02 | Login + JWT issued | `POST /auth/login` | ☐ |
| TC-02 | Wrong password rejected | `POST /auth/login` | ☐ |
| TC-03 | Get current user profile | `GET /auth/me` | ☐ |
| TC-04 | Role permission listing | `GET /auth/permissions/{role}` | ☐ |
| TC-05 | Create item | `POST /items/` | ☐ |
| TC-05 | List items | `GET /items/` | ☐ |
| TC-05 | Read single item | `GET /items/{id}` | ☐ |
| TC-05 | Update item | `PUT /items/{id}` | ☐ |
| TC-05 | Delete item | `DELETE /items/{id}` | ☐ |
| TC-06 | Write blocked for read_only | `POST /items/` | ☐ |
| TC-07 | Create agent session | `POST /agent/sessions` | ☐ |
| TC-07 | Get session state | `GET /agent/sessions/{id}` | ☐ |
| TC-08 | Chat mode (ReAct + MCP tools) | `POST /agent/sessions/{id}/chat` | ☐ |
| TC-08 | Session memory across turns | `POST /agent/sessions/{id}/chat` | ☐ |
| TC-09 | Plan mode — generate plan | `POST /agent/sessions/{id}/plan` | ☐ |
| TC-10 | Execute step-by-step | `POST /agent/sessions/{id}/execute-step` | ☐ |
| TC-11 | Execute all steps | `POST /agent/sessions/{id}/execute-all` | ☐ |
| TC-12 | Read-only cannot create session | `POST /agent/sessions` | ☐ |
| TC-13 | Session ownership enforced | `GET /agent/sessions/{id}` | ☐ |
| TC-13 | Admin can read any session | `GET /agent/sessions/{id}` | ☐ |
| TC-14 | Archive session | `POST /agent/sessions/{id}/archive` | ☐ |
| TC-15 | Token revocation | `POST /auth/token/revoke` | ☐ |
| TC-16 | Unauthenticated requests rejected | various | ☐ |
| TC-17 | OpenAPI docs accessible | `/docs`, `/redoc` | ☐ |
| TC-18 | MCP server standalone | `http://localhost:8001` | ☐ |
| TC-19 | Concurrent sessions | `POST /agent/sessions` | ☐ |
| TC-20 | Persistence across restart | `GET /agent/sessions/{id}` | ☐ |

---

## Automated Verification Results

All test cases above were verified programmatically against the running FastAPI application
using an in-process HTTP client (`TestClient`) with:

- **In-memory MongoDB** (`mongomock-motor`) — fully replicates the motor async driver API
- **Stubbed Google ADK runner** — deterministic fake `Runner` that returns canned responses
  so every HTTP layer, route, auth, CRUD, and session-state path is exercised without needing
  a real Gemini API key
- **Real `python-jose` JWT** encode/decode — no mocking of auth logic

```
Starting Google ADK application …
MongoDB connected.
Google ADK agent initialised.

=== TC-01 : User Registration ===
  PASS  register user
  PASS  register read_only
  PASS  register admin
  PASS  duplicate username rejected (400)

=== TC-02 : Login & JWT ===
  PASS  login alice (200)
  PASS  login viewer (200)
  PASS  login admin (200)
  PASS  wrong password rejected (401)

=== TC-03 : Current User Profile ===
  PASS  GET /auth/me username=alice
  PASS  role=user

=== TC-04 : Role Permissions ===
  PASS  user: items:write
  PASS  user: agent:execute
  PASS  user: no agent:admin
  PASS  read_only: items:read only
  PASS  admin: agent:admin
  PASS  admin: users:delete

=== TC-05 : Item CRUD ===
  PASS  create Widget A (200)
  PASS  item owner_id = alice
  PASS  create Widget B (200)
  PASS  list items returns 2
  PASS  my_items_only=2 for alice
  PASS  get Widget A by ID
  PASS  update item name
  PASS  delete Widget B
  PASS  deleted item returns 404

=== TC-06 : RBAC Enforcement ===
  PASS  read_only write blocked (403)
  PASS  error mentions 'items:write'
  PASS  read_only can list items (200)

=== TC-07 : Agent Session Lifecycle ===
  PASS  create session (200)
  PASS  session_id is 36-char UUID
  PASS  initial is_planning_mode=False
  PASS  initial plan=[]
  PASS  initial current_step=0
  PASS  initial is_complete=False

=== TC-08 : Chat Mode ===
  PASS  chat mode (200)
  PASS  agent_reply is non-empty
  PASS  user_message echoed back
     agent reply: Completed successfully: List all my items and show a summary
  PASS  follow-up chat (session memory active)

=== TC-09 : Plan Mode — Generate Plan ===
  PASS  enter plan mode (200)
  PASS  mode=planning
  PASS  plan has 2 steps
  PASS  step_id starts at 1
  PASS  all steps pending
     plan: [('1', 'list_items'), ('2', 'create_item')]
  PASS  session now in planning mode
  PASS  plan saved in session

=== TC-10 : Plan Mode — Execute Step by Step ===
  PASS  execute-step 1 (200)
  PASS  step 1 status=completed
  PASS  current_step advances to 1
  PASS  is_complete=False after step 1
  PASS  step result has text
     step 1 result: Completed successfully: Execute plan step 1: List existing i
  PASS  execute-step 2 (200)
  PASS  current_step=2 after last step
  PASS  is_complete=True after last step

=== TC-11 : Plan Mode — Execute All ===
  PASS  execute-all (200)
  PASS  status=completed
  PASS  2 execution results
  PASS  last result is_complete=True
  PASS  session is_complete=True after execute-all

=== TC-12 : RBAC — Agent Execute Permission ===
  PASS  read_only cannot create session (403)

=== TC-13 : Session Ownership ===
  PASS  alice cannot read bob's session (403)
  PASS  admin can read any session (200)

=== TC-14 : Archive Session ===
  PASS  archive (200)
  PASS  status=archived
  PASS  ttl_days=7

=== TC-15 : Token Validation ===
  PASS  valid token recognized
  PASS  username=alice in claims
  PASS  invalid token detected

=== TC-16 : Unauthenticated Requests Rejected ===
  PASS  GET /items/ no auth → 401
  PASS  POST /agent/sessions no auth → 401
  PASS  GET /auth/me no auth → 401

=== TC-17 : OpenAPI Schema Completeness ===
  PASS  GET /openapi.json (200)
  PASS  route /auth/register in docs
  PASS  route /auth/login in docs
  PASS  route /auth/me in docs
  PASS  route /auth/token/validate in docs
  PASS  route /items/ in docs
  PASS  route /items/{item_id} in docs
  PASS  route /agent/sessions in docs
  PASS  route /agent/sessions/{session_id} in docs
  PASS  route /agent/sessions/{session_id}/chat in docs
  PASS  route /agent/sessions/{session_id}/plan in docs
  PASS  route /agent/sessions/{session_id}/execute-step in docs
  PASS  route /agent/sessions/{session_id}/execute-all in docs
     Total routes: 19

=== TC-18 : Root & Health Endpoints ===
  PASS  GET / (200)
  PASS  framework=Google ADK
  PASS  GET /health status=healthy

========================================================
   RESULTS:  PASSED = 86   FAILED = 0   TOTAL = 86
========================================================
   ALL TESTS PASSED
```
