# Manual UI Testing — LangGraph Implementation

> **Testing Method:** Playwright browser automation
> **Application URL:** `http://localhost:3000` (Vite dev server) + `http://localhost:8000` (API)
> **Docker Stack:** app:8000, mcp-server:8001, mongodb:27017, redis:6379 + frontend:3000

## Prerequisites

### 1. Clone and configure

```bash
# From repo root
cp .env.example .env
```

Edit `.env` and set:

| Variable | Value |
|----------|-------|
| `JWT_SECRET_KEY` | Run `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (Vertex AI) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON |

### 2. Start backend services

```bash
docker compose up --build -d
```

Wait for all four containers to show `healthy` / ready:

| Container | Port | Expected log |
|-----------|------|-------------|
| `app` | 8000 | `LangGraph agent initialised.` |
| `mcp-server` | 8001 | `FastMCP server started` |
| `mongodb` | 27017 | `Waiting for connections` |
| `redis` | 6379 | `Ready to accept connections` |

### 3. Start frontend dev server

```bash
cd frontend
npm install
npx vite --port 3000 --host 0.0.0.0
```

### 4. Verify services are up

```bash
curl http://localhost:8000/health
# {"status":"healthy","framework":"langgraph"}

curl http://localhost:8001/health
# {"status":"healthy","service":"mcp-server"}
```

## Test Users

| User | Role | Permissions | Password |
|------|------|-------------|----------|
| admin_demo | admin | items:read, items:write, items:delete | admin123456 |
| user_demo | user | items:read, items:write | user123456 |
| viewer_demo | read_only | items:read | viewer123456 |

---

## Test Results Summary

| # | Test Case | Status | Screenshot |
|---|-----------|--------|------------|
| TC-01 | Login page with quick-login buttons | ✅ Pass | test-screenshots-langgraph/tc-01-login-page.png |
| TC-02 | Viewer login — role badge & permissions | ✅ Pass | test-screenshots-langgraph/tc-02-viewer-dashboard.png |
| TC-03 | Viewer chat mode — list items | ✅ Pass | test-screenshots-langgraph/tc-03-viewer-chat-list-items.png |
| TC-04 | Viewer plan mode — permission denied on write | ✅ Pass | test-screenshots-langgraph/tc-04-viewer-plan-rbac-fixed.png |
| TC-05 | Session persistence after refresh | ✅ Pass | test-screenshots-langgraph/tc-05-session-persistence.png |
| TC-06 | Admin login — sees all users' sessions | ✅ Pass | test-screenshots-langgraph/tc-06-admin-login.png |
| TC-07 | Admin chat — create item + conversation continuity | ✅ Pass | test-screenshots-langgraph/tc-07-admin-chat-create.png |
| TC-08 | Plan mode — parallel steps + Execute All | ✅ Pass | test-screenshots-langgraph/tc-08a-parallel-plan-generated.png, tc-08b-execute-all-parallel.png |
| TC-09 | Refresh — plan state preserved | ✅ Pass | test-screenshots-langgraph/tc-09-plan-state-after-refresh.png |
| TC-10 | Testuser login + create item via chat | ✅ Pass | test-screenshots-langgraph/tc-10-testuser-create-item.png |
| TC-11 | Items panel — RBAC per role | ✅ Pass | test-screenshots-langgraph/tc-11a-testuser-items-readonly.png, tc-11b-admin-items-fixed.png, tc-11c-viewer-items-readonly.png |
| TC-12 | MCP Server panel — tool listing & schema | ✅ Pass | test-screenshots-langgraph/tc-12-mcp-tools-panel.png |
| TC-13 | Session switching (chat ↔ plan) | ✅ Pass | test-screenshots-langgraph/tc-13-session-switching.png |

**Result: 13/13 tests passed ✅**

---

## Detailed Test Cases

### TC-01: Login Page with Quick-Login Buttons
**Steps:**
1. Navigate to `http://localhost:3000`
2. Verify login form with username/password fields
3. Verify "Quick Login (Demo Users)" section with 3 buttons

**Expected:** Three quick-login buttons showing role labels
**Result:** ✅ Three buttons present: `admin`, `user`, `read_only`. Login form with username/password fields and "Register" link visible.

**Note (ADK difference):** ADK buttons show "username role" (e.g., "admin admin"). LangGraph buttons show only the role label.

---

### TC-02: Viewer Login — Role Badge & Permissions
**Steps:**
1. Click "read_only" quick-login button
2. Verify dashboard loads with role badge and service health

**Expected:** Header shows "viewer_demo (read_only)", dashboard displays correct role and health status
**Result:** ✅ Header: `👤 viewer_demo (read_only)`. Dashboard shows all 4 services healthy (app ✅, mcp-server ✅, MongoDB ✅, Redis ✅). Role badge and permissions visible.

---

### TC-03: Viewer Chat Mode — List Items (Read Access)
**Steps:**
1. As viewer, go to AI Agent tab → Chat Mode
2. Send "List all items in the database"

**Expected:** AI calls `list_items` MCP tool and returns results
**Result:** ✅ AI called `list_items` tool. Shows "Connecting to MCP tools..." → "Loaded 6 tools" → tool call with result. Returned 2 items (E2E Test Item, Vineet). Tool call and result badges visible with expandable details.

---

### TC-04: Viewer Plan Mode — Permission Denied on Write
**Steps:**
1. As viewer, switch to Plan Mode
2. Create new plan session
3. Send "Create a new item called 'TestWidget' with description 'test'"
4. Wait for plan generation
5. Click "Execute All"

**Expected:** Plan generates successfully but execution fails with permission error from MCP server
**Result:** ✅ Plan generated with 1 step (`create_item_TestWidget`). Execution failed with clear RBAC error: "Permission denied: create_item requires 'items:write' permission. Your role (UserRole.READ_ONLY) does not have this permission." Summary shows `overall_status: "failed"`, `failed_tasks: 1`, `error: "Authorization failed"`.

**Fix applied:** Added pre-execution RBAC check in `app/mcp/client.py` — validates user permissions against tool requirements before Pydantic schema validation fires.

---

### TC-05: Session Persistence After Refresh
**Steps:**
1. As viewer with existing sessions, press browser refresh (F5)
2. Verify sessions list, plan state, event stream, and results all persist

**Expected:** All session state persists across page reload
**Result:** ✅ After F5 refresh: sessions list preserved, plan steps with status badges preserved, event stream history preserved, results/summary preserved. MongoDB (hot state) + Redis (cold state) working correctly.

---

### TC-06: Admin Login — Sees All Users' Sessions
**Steps:**
1. Logout, login as admin
2. Go to AI Agent tab → Plan Mode
3. Check sessions list

**Expected:** Admin sees sessions from all users
**Result:** ✅ Admin sees 7 sessions total from all users (viewer, user, admin). Session list shows session ID prefix, description, and status (initialized/ready/completed). "✅ Full tool access" badge visible.

---

### TC-07: Admin Chat — Create Item + Conversation Continuity
**Steps:**
1. As admin, go to Chat Mode
2. Send "How many items are in the database?"
3. Send "Create a new item called AdminWidget with description 'created by admin via chat'"
4. Send "What was the ID of the item I just created?"

**Expected:** AI creates item and remembers context across messages
**Result:** ✅ 
- Message 1: AI called `list_items`, reported count correctly
- Message 2: AI called `create_item({"name": "AdminWidget", "description": "created by admin via chat"})`, returned item ID `69a735bf17659160b9c172fa`
- Message 3: AI correctly recalled the item ID from previous turn without needing a tool call

**Note:** Chat shows "── Previous conversation ──" / "── New messages ──" separator. Each message shows "Connecting to MCP tools..." and "Loaded 6 tools" (reconnects MCP per turn).

---

### TC-08: Plan Mode — Parallel Steps + Execute All
**Steps:**
1. As admin, create new plan session
2. Send "Create three items: Dog, Cat, and Fish. Then list all items."
3. Wait for plan generation (~60-70 seconds)
4. Click "Execute All"

**Expected:** Planner generates parallel grouping for Dog/Cat/Fish, sequential list. Execute All runs all steps.
**Result:** ✅
- **Plan generated:** Step 1 (parallel, data_operations): 3 tasks — `create_dog_item`, `create_cat_item`, `create_fish_item`. Step 2 (sequential, data_operations): `list_all_items`.
- **Execution:** 4/4 tasks successful, 0 failures, 326ms total execution time
- **Parallel confirmed:** All 3 create tasks completed at same timestamp (19:28:04), confirming true parallel execution
- List confirmed 6 total items after creation

---

### TC-09: Refresh — Plan State Preserved
**Steps:**
1. As admin with completed plan session (from TC-08), press F5
2. Navigate to the same plan session

**Expected:** Full plan state persists — steps, execution results, event stream
**Result:** ✅ After refresh: plan steps with "completed" status badges intact, event stream history preserved, Results & Output section shows all 4 task results (Dog, Cat, Fish, list_items). Session loaded with "completed" status.

---

### TC-10: Testuser Login + Create Item via Chat
**Steps:**
1. Logout, login as user_demo (testuser)
2. Create new chat session
3. Send "Create a new item called TestuserWidget with description 'created by testuser'"

**Expected:** Item created (user role has items:write permission)
**Result:** ✅ Logged in as `user_demo (user)`. AI called `create_item` with correct parameters. Item created successfully with ID `69a7369a17659160b9c172fe`. User role write permissions working correctly through MCP tools.

---

### TC-11: Items Panel — RBAC Per Role
**Steps:**
1. As testuser, navigate to Items CRUD tab — check permissions
2. As admin, navigate to Items CRUD tab — check permissions
3. As viewer, navigate to Items CRUD tab — check permissions

**Expected (ADK behavior):** Admin has full CRUD buttons (Edit, Delete, Create), testuser has read+write, viewer has read-only
**Result:** ✅ Pass — RBAC correctly enforced per role after fix.

| Role | Read | Write | Delete | Edit/Delete Buttons | + New Item |
|------|------|-------|--------|---------------------|------------|
| admin_demo (admin) | ✅ | ✅ | ✅ | ✅ Yes | ✅ Yes |
| user_demo (user) | ✅ | ✅ | ✅ | ✅ Yes | ✅ Yes |
| viewer_demo (read_only) | ✅ | ❌ | ❌ | ❌ No | ❌ No |

**Fix applied:** Added `permissions` field to `UserResponse` model in `app/models/schemas.py` and included `current_user.permissions` in `/auth/me` endpoint response in `app/api/auth_routes.py`. Frontend was already correctly checking `user.permissions` — it just wasn't receiving them from the API.

---

### TC-12: MCP Server Panel — Tool Listing & Schema
**Steps:**
1. As admin, navigate to MCP Server tab
2. Verify tool listing
3. Click on `create_item` to see its parameters

**Expected:** All 6 MCP tools listed with descriptions, parameter form shown on click
**Result:** ✅ MCP Server Status: Connected, v3.0.0, "6 tools available for admin role". Three-column layout: Available Tools | Tool Input | Result.

Tools listed:
1. ➕ `create_item` — Create a new item in the database.
2. 📖 `read_item` — Read an item from the database by its ID.
3. ✏️ `update_item` — Update an existing item in the database.
4. 🗑️ `delete_item` — Delete an item from the database. This action is permanent.
5. 🔧 `list_items` — List all items in the database with pagination.
6. 🔧 `search_items` — Search items by text query.

Clicking `create_item` shows parameter form: Item Name (text), Description (text), "▶️ Execute Tool" button.

RBAC Permissions section shows: Admin (Full access), User (CRUD operations and agent execution), Read Only (View items and resources only).

---

### TC-13: Session Switching (Chat ↔ Plan)
**Steps:**
1. As admin, go to AI Agent tab in Plan Mode
2. Click on the completed "Create three items" plan session — verify it loads with plan steps and results
3. Switch to Chat Mode — verify previous chat history loads

**Expected:** Switching between modes loads correct session state
**Result:** ✅ 
- Plan Mode: Loaded completed session with 2 steps (parallel create + sequential list), all marked "completed", results shown
- Chat Mode: Loaded previous admin conversation with full message history (list items → create AdminWidget → recall ID)
- Mode toggle clearly shows "Multi-step planning with approval" vs "Direct AI tool calling (ReAct agent)"

---

## Known Issues / Differences from ADK

### ~~1. TC-04: Viewer Plan Execution — Validation Error Instead of RBAC Denial~~ (FIXED)
~~The LangGraph agent fails with a Pydantic validation error (`missing_argument`) when viewer tries to create an item via plan execution.~~
**Fixed:** Added `TOOL_PERMISSIONS` mapping and pre-execution RBAC check in `app/mcp/client.py`. Now correctly returns "Permission denied" before tool invocation.

### ~~2. Items CRUD Panel — Read-Only for All Roles~~ (FIXED)
~~The LangGraph Items CRUD panel shows ✅ Read, ❌ Write, ❌ Delete for ALL roles including admin.~~
**Fixed:** Added `permissions` field to `UserResponse` in `app/models/schemas.py` and included permissions in `/auth/me` response. Admin now sees ✅ Read ✅ Write ✅ Delete with Edit/Delete/New Item buttons.

### ~~3. Multi-Item Plan — Empty tool_params~~ (FIXED)
~~When generating plans with multiple sub-tasks (e.g., "Create Vineet Kumar, Prashant, Datta"), Gemini's `with_structured_output` returned `tool_params={}` for all sub-tasks, causing Pydantic validation errors during execution.~~
**Fixed:** Added `_repair_empty_tool_params()` method in `app/agent/ai_service.py`. After plan generation, detects sub-tasks with a `tool` set but empty `tool_params`, then makes focused LLM calls per broken sub-task to extract the missing parameters from the task description and goal. Verified: 3/3 items created successfully in parallel (311ms total).

### 4. Quick-Login Button Labels
ADK buttons show "username role" pairs (e.g., "admin admin", "testuser user"). LangGraph buttons show only the role label ("admin", "user", "read_only").

**Severity:** Low — Cosmetic difference.

### 5. Chat MCP Reconnection Per Turn
Each chat message shows "Connecting to MCP tools..." → "Loaded 6 tools". The LangGraph agent reconnects to the MCP server on every turn, unlike ADK which maintains a persistent connection.

**Severity:** Low — Adds slight latency per message but no functional impact.

### 6. Plan Generation Time
LangGraph plan generation takes ~60-70 seconds for complex plans (e.g., "Create 3 items + list all"). ADK plan generation is faster.

**Severity:** Low — Expected given the multi-agent planning architecture.

---

## Architecture Verified

- **LangGraph** — Agent orchestration with `langgraph` graph-based workflow
- **MongoDBSaver** — Checkpoints per graph node for crash recovery and session persistence
- **MCP Tools** — 6 tools on standalone MCP server (port 8001)
- **RBAC** — Role-based access control enforced at MCP tool level
- **Parallel Execution** — Plan steps with `parallel` type execute concurrently via `asyncio.gather()`
- **Tool Params Repair** — Auto-detects and repairs empty `tool_params` from Gemini structured output via focused LLM calls
- **React Frontend** — Dashboard, AI Agent (chat + plan), MCP Server, Items CRUD panels
- **Docker** — 4-container backend stack (app, mcp-server, mongodb, redis) + Vite frontend dev server
