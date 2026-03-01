# System Architecture

This document describes the architecture of the AI Experiments MCP Demo Application.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    FRONTEND                                         │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         React UI (Port 3000)                                   │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐                   │ │
│  │  │Dashboard │  │AI Agent  │  │MCP Server│  │  Items CRUD  │                   │ │
│  │  │  Panel   │  │  Panel   │  │  Panel   │  │    Panel     │                   │ │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘                   │ │
│  │       │              │             │               │                           │ │
│  │       └──────────────┴─────────────┴───────────────┘                           │ │
│  │                              │                                                  │ │
│  │                    HTTP/SSE Requests                                           │ │
│  └──────────────────────────────┼──────────────────────────────────────────────────┘ │
└─────────────────────────────────┼────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (Port 8000)                                     │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         FastAPI Application                                     │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                    Request Logging Middleware                           │   │ │
│  │  │  • Logs all incoming requests with request ID                           │   │ │
│  │  │  • Tracks response time and status                                      │   │ │
│  │  │  • Adds X-Request-ID header to responses                                │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                    │                                            │ │
│  │  ┌─────────────────────────────────┴───────────────────────────────────────┐   │ │
│  │  │                           API Routers                                   │   │ │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │ │
│  │  │  │  /auth   │  │ /items   │  │ /agent   │  │  /mcp    │  │ /stream  │   │   │ │
│  │  │  │          │  │          │  │          │  │          │  │   (SSE)  │   │   │ │
│  │  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │   │ │
│  │  └───────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────┘   │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                      Authorization Layer                                │   │ │
│  │  │  • JWT Token Validation                                                 │   │ │
│  │  │  • Role-Based Access Control (admin, user, read_only)                   │   │ │
│  │  │  • Permission Checking (items:read/write/delete, agent:*, mcp:*)        │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         Multi-Agent Orchestrator                               │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                        AI Service (Vertex AI)                           │   │ │
│  │  │  • generate_plan() - AI-powered plan generation                         │   │ │
│  │  │  • execute_task() - AI-powered task execution                           │   │ │
│  │  │  • analyze_for_mcp() - Determine which MCP tools to use                 │   │ │
│  │  │  • generate_summary() - AI-powered execution summary                    │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                    │                                            │ │
│  │  ┌─────────────────────────────────┴───────────────────────────────────────┐   │ │
│  │  │                     Agent Types & Execution Modes                       │   │ │
│  │  │                                                                         │   │ │
│  │  │  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐   │   │ │
│  │  │  │ Research Agent   │    │ Execution Agent  │    │ Validation Agent │   │   │ │
│  │  │  │ (can run in      │    │ (sequential      │    │ (sequential      │   │   │ │
│  │  │  │  parallel)       │    │  execution)      │    │  execution)      │   │   │ │
│  │  │  └──────────────────┘    └──────────────────┘    └──────────────────┘   │   │ │
│  │  │                                                                         │   │ │
│  │  │  Execution Modes:                                                       │   │ │
│  │  │  • PARALLEL: Multiple tasks run concurrently (e.g., research phase)     │   │ │
│  │  │  • SEQUENTIAL: Tasks run one after another (e.g., execution phase)      │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              MCP Server                                        │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                         Available Tools                                 │   │ │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │   │ │
│  │  │  │ create_item  │  │  get_item    │  │ list_items   │                   │   │ │
│  │  │  │ (mcp:write)  │  │ (mcp:read)   │  │ (mcp:read)   │                   │   │ │
│  │  │  └──────────────┘  └──────────────┘  └──────────────┘                   │   │ │
│  │  │  ┌──────────────┐  ┌──────────────┐                                     │   │ │
│  │  │  │ update_item  │  │ delete_item  │                                     │   │ │
│  │  │  │ (mcp:write)  │  │ (mcp:delete) │                                     │   │ │
│  │  │  └──────────────┘  └──────────────┘                                     │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                              │
│                                                                                      │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐               │
│  │        MongoDB               │    │          Redis               │               │
│  │    (Hot State Storage)       │    │    (Cold State Storage)      │               │
│  │                              │    │                              │               │
│  │  • Agent session state       │    │  • Archived checkpoints      │               │
│  │  • Current execution plan    │    │  • Session cache             │               │
│  │  • Task results              │    │  • Token blacklist           │               │
│  │  • User data                 │    │                              │               │
│  │  • Items collection          │    │                              │               │
│  └──────────────────────────────┘    └──────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL SERVICES                                         │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    Google Cloud Platform - Vertex AI                          │   │
│  │                                                                               │   │
│  │  • Model: Gemini 2.5 Pro                                                      │   │
│  │  • Authentication: Service Account JSON                                       │   │
│  │  • Region: us-central1 (configurable)                                         │   │
│  │                                                                               │   │
│  │  AI Capabilities:                                                             │   │
│  │  ├── Plan Generation: Analyzes goals, creates structured execution plans     │   │
│  │  ├── Task Execution: Executes individual tasks with context awareness        │   │
│  │  ├── MCP Analysis: Determines which tools to use for a goal                  │   │
│  │  └── Summary Generation: Creates execution summaries                          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Plan Generation Flow

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐
│  User    │───▶│  React   │───▶│   FastAPI    │───▶│ Multi-   │───▶│ Vertex   │
│  Input   │    │  UI      │    │   Backend    │    │ Agent    │    │ AI       │
│ (Goal)   │    │          │    │   (SSE)      │    │ Orch.    │    │ Gemini   │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └──────────┘
                     │                 │                  │               │
                     │                 │                  │               │
                     │  SSE Stream     │                  │               │
                     │◀────────────────│◀─────────────────│◀──────────────│
                     │                 │                  │               │
                     │  Events:        │                  │               │
                     │  - status       │                  │               │
                     │  - thinking     │                  │               │
                     │  - plan_step    │                  │               │
                     │  - plan_complete│                  │               │
                     ▼                 ▼                  ▼               ▼
```

### 2. Plan Execution Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          Plan Execution Pipeline                                  │
│                                                                                   │
│  Step 1: Research Phase (PARALLEL)                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │ │
│  │  │ AI Task 1    │  │ AI Task 2    │  │ AI Task 3    │   Running in parallel │ │
│  │  │ Search DB    │  │ Query APIs   │  │ Analyze Data │                       │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 2: Analysis Phase (SEQUENTIAL)                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐                                       │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │   Tasks run one after another        │ │
│  │  │ Process Data │    │ Extract      │   with context from previous         │ │
│  │  └──────────────┘    └──────────────┘                                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 3: Execution Phase (SEQUENTIAL)                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │───▶│ AI Task 3    │                   │ │
│  │  │ Prepare      │    │ Execute      │    │ Post-process │                   │ │
│  │  └──────────────┘    └──────────────┘    └──────────────┘                   │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 4: Data Operations Phase (SEQUENTIAL with MCP)                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │ │
│  │  │ Validate     │───▶│ Call MCP     │───▶│ Verify       │                   │ │
│  │  │ Data         │    │ Tools        │    │ Results      │                   │ │
│  │  └──────────────┘    └──────────────┘    └──────────────┘                   │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 5: Validation Phase (SEQUENTIAL)                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐                                       │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │                                       │ │
│  │  │ Verify       │    │ Generate     │                                       │ │
│  │  │ Outputs      │    │ Summary      │                                       │ │
│  │  └──────────────┘    └──────────────┘                                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Logging Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Structured Logging                                      │
│                                                                                      │
│  Every request/response is logged with:                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │  {                                                                              │ │
│  │    "timestamp": "2024-01-15T10:30:45.123Z",                                     │ │
│  │    "level": "INFO",                                                             │ │
│  │    "request_id": "abc12345",        // Unique per request                       │ │
│  │    "session_id": "xyz78901",        // Agent session ID                         │ │
│  │    "user_id": "user123",            // Authenticated user                       │ │
│  │    "agent_type": "planning",        // Which agent is active                    │ │
│  │    "phase": "research",             // Current execution phase                  │ │
│  │    "message": "AI Request to gemini-2.5-pro",                                   │ │
│  │    "data": {                        // Additional context                       │ │
│  │      "prompt_preview": "...",                                                   │ │
│  │      "goal": "..."                                                              │ │
│  │    },                                                                           │ │
│  │    "duration_ms": 1234              // For timing-related logs                  │ │
│  │  }                                                                              │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  Log Categories:                                                                     │
│  • 📥 Request received                                                              │
│  • 📤 Response sent                                                                 │
│  • 🤖 AI request/response                                                           │
│  • 🚀 Agent started                                                                 │
│  • ✅ Agent completed                                                               │
│  • 📍 Step started                                                                  │
│  • ✓ Step completed                                                                │
│  • ⚡ Parallel execution                                                            │
│  • 📋 Sequential execution                                                          │
│  • ❌ Errors                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Authentication & Authorization

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              RBAC System                                             │
│                                                                                      │
│  Roles:                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │  admin     │ items:* agent:* mcp:*                     │ Full access            │ │
│  │  user      │ items:read,write,delete agent:* mcp:r,w   │ Standard user         │ │
│  │  read_only │ items:read mcp:read                       │ View only             │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  Token Flow:                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│  │  Login   │───▶│ Generate │───▶│  Include │───▶│ Validate │                       │
│  │ Request  │    │ JWT      │    │ in Header│    │ & Check  │                       │
│  └──────────┘    └──────────┘    └──────────┘    │ Perms    │                       │
│                                                   └──────────┘                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Checkpoint Storage

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         State Management                                             │
│                                                                                      │
│  Hot State (MongoDB):                      Cold State (Redis):                       │
│  ┌──────────────────────────────┐         ┌──────────────────────────────┐          │
│  │ • Active sessions            │         │ • Completed sessions          │          │
│  │ • In-progress plans          │ ──────▶ │ • Archived checkpoints        │          │
│  │ • Current execution state    │ (after  │ • Historical data             │          │
│  │ • Real-time updates          │  done)  │ • Session cache               │          │
│  └──────────────────────────────┘         └──────────────────────────────┘          │
│                                                                                      │
│  Checkpoint Structure:                                                               │
│  {                                                                                   │
│    "session_id": "uuid",                                                            │
│    "user_id": "user123",                                                            │
│    "state_type": "hot|cold",                                                        │
│    "state_data": { ... plan, tasks, results ... },                                  │
│    "created_at": "timestamp",                                                       │
│    "updated_at": "timestamp"                                                        │
│  }                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Docker Deployment

```yaml
services:
  app:           # FastAPI Backend (Port 8000)
  mongodb:       # Hot State Storage (Port 27017)
  redis:         # Cold State Storage (Port 6379)
  frontend:      # React UI (Port 3000) - optional

# Environment:
# - GOOGLE_APPLICATION_CREDENTIALS: Service account JSON
# - GOOGLE_CLOUD_PROJECT: GCP project ID
# - JWT_SECRET_KEY: For token signing
# - MONGODB_URL: MongoDB connection string
# - REDIS_URL: Redis connection string
```
