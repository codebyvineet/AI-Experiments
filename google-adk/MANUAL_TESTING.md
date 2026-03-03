# Manual UI Testing — Google ADK Implementation

> **Testing Method:** Playwright browser automation
> **Application URL:** `http://localhost:8000/app/`
> **Docker Stack:** app:8000, mcp-server:8001, mongodb:27017, redis:6379

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

curl http://localhost:8001/health
# {"status":"healthy","service":"mcp-server"}
```

## Test Users

| User | Role | Permissions | Password |
|------|------|-------------|----------|
| admin | admin | items:read, items:write, items:delete | admin123456 |
| testuser | user | items:read, items:write | user123456 |
| viewer | read_only | items:read | viewer123456 |

---

## Test Results Summary

| # | Test Case | Status | Screenshot |
|---|-----------|--------|------------|
| TC-01 | Login page with quick-login buttons | ✅ Pass | test-screenshots/tc-01-login-page.png |
| TC-02 | Viewer login — role badge & permissions | ✅ Pass | test-screenshots/tc-02-viewer-dashboard.png |
| TC-03 | Viewer chat mode — list items | ✅ Pass | test-screenshots/tc-03-viewer-chat-list-items.png |
| TC-04 | Viewer plan mode — permission denied on write | ✅ Pass | test-screenshots/tc-04-viewer-plan-permission-denied.png |
| TC-05 | Session persistence after refresh | ✅ Pass | test-screenshots/tc-05-session-persistence.png |
| TC-06 | Admin login — sees all users' sessions | ✅ Pass | test-screenshots/tc-06-admin-login.png |
| TC-07a | Admin chat — create item via tool | ✅ Pass | test-screenshots/tc-07a-admin-chat-create.png |
| TC-07b | Admin chat — conversation continuity | ✅ Pass | test-screenshots/tc-07b-admin-chat-continuity.png |
| TC-08a | Plan mode — parallel steps generated | ✅ Pass | test-screenshots/tc-08a-parallel-plan-generated.png |
| TC-08b | Plan mode — Execute Next Step (single) | ✅ Pass | test-screenshots/tc-08b-execute-next-step.png |
| TC-08c | Plan mode — Execute All (parallel) | ✅ Pass | test-screenshots/tc-08c-execute-all-parallel.png |
| TC-09a | Refresh — chat context preserved | ✅ Pass | test-screenshots/tc-09a-refresh-context-preserved.png |
| TC-09b | Refresh — plan state preserved | ✅ Pass | test-screenshots/tc-09b-plan-state-preserved.png |
| TC-10a | Testuser login + chat | ✅ Pass | test-screenshots/tc-10a-testuser-chat.png |
| TC-10b | Testuser — create item via chat | ✅ Pass | test-screenshots/tc-10b-testuser-create-item.png |
| TC-11a | Items panel — admin full CRUD | ✅ Pass | test-screenshots/tc-11a-items-admin-crud.png |
| TC-11b | Items panel — viewer read-only | ✅ Pass | test-screenshots/tc-11b-items-viewer-readonly.png |
| TC-12 | MCP Server panel — tool listing & schema | ✅ Pass | test-screenshots/tc-12-mcp-tools-panel.png |
| TC-13 | Session switching (chat ↔ plan) | ✅ Pass | test-screenshots/tc-13-session-switching.png |

**Result: 19/19 tests passed ✅**

---

## Detailed Test Cases

### TC-01: Login Page with Quick-Login Buttons
**Steps:**
1. Navigate to `http://localhost:8000/app/`
2. Verify login form with username/password fields
3. Verify "Quick Login (Demo Users)" section with 3 buttons

**Expected:** Three quick-login buttons showing username and role (admin/admin, testuser/user, viewer/read_only)
**Result:** ✅ All three buttons present with correct labels

---

### TC-02: Viewer Login — Role Badge & Permissions
**Steps:**
1. Click "viewer read_only" quick-login button
2. Verify dashboard loads with role badge

**Expected:** Header shows "viewer read_only", dashboard displays correct role and permissions
**Result:** ✅ `read_only` badge displayed, permissions show items:read ✅, items:write ❌

---

### TC-03: Viewer Chat Mode — List Items (Read Access)
**Steps:**
1. As viewer, go to AI Agent tab
2. Create new chat session
3. Send "List all items in the database"

**Expected:** AI calls `list_items` MCP tool and returns results
**Result:** ✅ AI called `list_items`, returned all items in database. Tool call and result badges visible.

---

### TC-04: Viewer Plan Mode — Permission Denied on Write
**Steps:**
1. As viewer, switch to Plan Mode
2. Create new plan session
3. Send "Create a new item called 'Playwright Test Widget' with description 'Created during UI testing'"
4. Wait for plan generation
5. Click "Execute All"

**Expected:** Plan generates successfully but execution fails with permission error from MCP server
**Result:** ✅ Plan generated with steps. Execution failed: "Error creating item. It seems the viewer role does not have write permissions." RBAC enforced at MCP tool level.

---

### TC-05: Session Persistence After Refresh
**Steps:**
1. As viewer with existing sessions, press browser refresh (F5)
2. Verify sessions list still shows all previous sessions

**Expected:** All sessions persist and are listed after page reload
**Result:** ✅ 5 sessions persisted across refresh (both chat and plan types)

---

### TC-06: Admin Login — Sees All Users' Sessions
**Steps:**
1. Logout, login as admin
2. Go to AI Agent tab
3. Check sessions list

**Expected:** Admin sees sessions from all users (admin is the only role that sees all)
**Result:** ✅ Admin sees all sessions including those from other users' testing

---

### TC-07a: Admin Chat — Create Item via MCP Tool
**Steps:**
1. As admin, create new chat session
2. Send "Create a new item called AdminWidget with description 'created by admin via chat'"

**Expected:** AI calls `create_item` tool, item is created
**Result:** ✅ Tool call `create_item` with `{"name": "AdminWidget", "description": "created by admin via chat"}` succeeded. Tool result badge shows success with item ID.

---

### TC-07b: Admin Chat — Conversation Continuity
**Steps:**
1. In same session as TC-07a, send follow-up: "What was the ID of the item I just created?"

**Expected:** AI remembers context and returns the item ID
**Result:** ✅ AI correctly recalled item ID from previous turn. Session state preserved within conversation.

---

### TC-08a: Plan Mode — Parallel Steps Generated
**Steps:**
1. As admin, create new plan session
2. Send "Create three items: Dog, Cat, and Fish. Then list all items."

**Expected:** Planner generates steps with parallel grouping — Dog/Cat/Fish in same group, list_items in separate group
**Result:** ✅ Plan generated with 4 steps: Steps 1-3 (Dog, Cat, Fish) in group 1 (parallel), Step 4 (list_items) in group 2 (sequential). Parallel grouping correctly identified.

---

### TC-08b: Plan Mode — Execute Next Step (Single)
**Steps:**
1. From TC-08a, click "Execute Next Step"

**Expected:** Only one step executes
**Result:** ✅ Single step executed (Dog created), remaining steps still pending with "Execute Next Step" and "Execute All" buttons available.

---

### TC-08c: Plan Mode — Execute All (Parallel Execution)
**Steps:**
1. From TC-08b, click "Execute All"

**Expected:** Remaining steps execute — Cat and Fish run in parallel (same group), then list_items runs
**Result:** ✅ All remaining steps executed. Cat and Fish created concurrently (parallel group 1 remaining), then list_items confirmed all items exist. Final item count includes Dog, Cat, Fish.

**Note:** One stale session warning observed during parallel execution — this is expected when concurrent runners write to the same MongoDB session simultaneously. Items were still created successfully via MCP tools despite the session state race condition.

---

### TC-09a: Refresh — Chat Context Preserved
**Steps:**
1. As admin with active chat session (from TC-07a), refresh page
2. Select the same session
3. Send "What item did I create earlier?"

**Expected:** AI remembers context from before refresh
**Result:** ✅ AI correctly recalled the item created pre-refresh. MongoDB session persistence working correctly via MongodbSessionService.

**Note:** Chat message history UI is not visually reconstructed on reload (the messages array in frontend state is lost), but server-side context is fully preserved. This is a frontend limitation — the ADK session events are stored in MongoDB but the frontend doesn't reconstruct the visual message history from them.

---

### TC-09b: Refresh — Plan State Preserved
**Steps:**
1. As admin with plan session (from TC-08), refresh page
2. Navigate to the plan session

**Expected:** Plan session state persists — execute buttons should be available if plan was in progress
**Result:** ✅ Plan session loaded after refresh with "Planning" status badge visible. Execute buttons available. Session state (`is_planning_mode`, plan data) preserved in MongoDB.

---

### TC-10a: Testuser Login + Chat
**Steps:**
1. Logout, login as testuser
2. Create new chat session
3. Send "List all items"

**Expected:** Testuser (user role) can chat and access read tools
**Result:** ✅ Logged in as testuser with `user` badge. Chat session created. AI called `list_items` and returned 21 items. No permission warnings.

---

### TC-10b: Testuser — Create Item via Chat
**Steps:**
1. As testuser, send "Create a new item called TestuserWidget with description 'created by testuser'"

**Expected:** Item created (user role has items:write permission)
**Result:** ✅ `create_item` tool called with correct parameters. Item created successfully. User role write permissions working correctly.

---

### TC-11a: Items Panel — Admin Full CRUD
**Steps:**
1. As admin, navigate to Items tab

**Expected:** All items listed with Edit and Delete buttons, + Create Item button at top
**Result:** ✅ Items panel shows all 22 items. Permission badge: admin ✅ Read ✅ Write ✅ Delete. Each item has Edit and Delete buttons. "+ Create Item" button visible at top.

---

### TC-11b: Items Panel — Viewer Read-Only
**Steps:**
1. As viewer, navigate to Items tab

**Expected:** Items listed but no create/edit/delete controls
**Result:** ✅ Items listed in read-only mode. Permission badge: read_only ✅ Read ❌ Write ❌ Delete. Warning banner: "⚠️ Write operations will be denied". No Edit/Delete buttons on items. No "+ Create Item" button.

---

### TC-12: MCP Server Panel — Tool Listing & Schema
**Steps:**
1. Navigate to MCP Server tab
2. Click on a tool to see its parameters

**Expected:** All 6 MCP tools listed with descriptions, parameter schemas shown on click
**Result:** ✅ 6 tools listed: create_item, read_item, update_item, delete_item, list_items, search_items. Three-column layout: tool list | parameters | results. Clicking `create_item` shows parameter form with name* (string, required), description (string), data (object). "▶ Execute Tool" button available. Role permissions badge shown (viewer: ✅ Read tools, ❌ Execute write tools).

---

### TC-13: Session Switching (Chat ↔ Plan)
**Steps:**
1. As admin, go to AI Agent tab
2. Click on a chat session
3. Click on a different plan session
4. Verify session ID changes and correct mode loads

**Expected:** Switching between sessions loads correct session state and mode
**Result:** ✅ Clicked chat session — loaded in chat mode. Switched to plan session — loaded with "Planning" status badge. Session ID in header updated correctly. Sessions list shows mix of chat/plan types with Active/Planning status badges.

---

## Known Issues / Limitations

1. **Chat history not visually reconstructed on refresh** — Server-side context is fully preserved (AI remembers conversation), but the frontend doesn't reconstruct the visual message history from ADK session events stored in MongoDB. After refresh, the chat area appears empty until new messages are sent.

2. **Plan step status badges stay "pending" after execution** — The plan object in the frontend messages array isn't updated after step execution. Steps show as executed in the response messages but the original plan display still shows "pending" badges.

3. **Parallel execution stale session warning** — When parallel runners write to the same MongoDB session concurrently, one runner may encounter a "last_update_time is earlier than storage_session" error. This is a race condition in MongodbSessionService. Items are still created successfully via MCP tools — only the session state write is affected.

---

## Architecture Verified

- **Google ADK** — Agent orchestration with `google.adk.agents.Agent` and `SequentialAgent`
- **MongodbSessionService** — Session persistence in MongoDB (verified via refresh tests)
- **MCP Tools** — 6 tools on standalone MCP server (port 8001) via `McpToolset`
- **RBAC** — Role-based access control enforced at MCP tool level (viewer denied writes)
- **Parallel Execution** — Steps grouped by `group` field, executed via `asyncio.gather()`
- **React Frontend** — Dashboard, AI Agent (chat + plan), MCP Server, Items panels
- **Docker** — 4-container stack (app, mcp-server, mongodb, redis)
