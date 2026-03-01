# AI-Experiments

A containerized Python application demonstrating MCP Server, LangGraph agent with plan mode, and JWT-based RBAC authentication.

## Features

- **MCP Server**: Model Context Protocol server with tools and resources
- **LangGraph Agent**: Agentic system with plan mode for multi-step task execution
- **Hot State Checkpoints**: MongoDB storage for active agent sessions
- **Cold State Checkpoints**: Redis storage for archived/inactive sessions
- **CRUD Operations**: Full create, read, update, delete operations for items
- **JWT Authentication**: Secure token-based authentication
- **RBAC Authorization**: Role-based access control with permissions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
├─────────────────────────────────────────────────────────────┤
│  Auth API  │  Items API  │  Agent API  │  MCP Server API    │
├─────────────────────────────────────────────────────────────┤
│                  Authorization Layer (RBAC)                  │
├─────────────────────────────────────────────────────────────┤
│         LangGraph Agent         │       MCP Server          │
│       (Plan Mode Support)       │    (Tools & Resources)    │
├─────────────────────────────────────────────────────────────┤
│    MongoDB (Hot State)    │    Redis (Cold State)           │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Using Docker Compose

1. Clone the repository:
```bash
git clone https://github.com/codebyvineet/AI-Experiments.git
cd AI-Experiments
```

2. Create a `.env` file from the example:
```bash
cp .env.example .env
```

3. Update the `.env` file with your settings (especially `JWT_SECRET_KEY`)

4. Start the application:
```bash
docker-compose up -d
```

5. Access the API documentation at `http://localhost:8000/docs`

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Start MongoDB and Redis (using Docker):
```bash
docker run -d -p 27017:27017 mongo:7.0
docker run -d -p 6379:6379 redis:7-alpine
```

3. Run the application:
```bash
uvicorn app.main:app --reload
```

## API Endpoints

### Authentication (`/auth`)
- `POST /auth/register` - Register a new user
- `POST /auth/login` - Login and get access token
- `POST /auth/token/generate` - Generate token (internal API for MCP RBAC)
- `POST /auth/token/validate` - Validate a token
- `POST /auth/token/revoke` - Revoke a token
- `GET /auth/me` - Get current user info
- `GET /auth/permissions/{role}` - Get permissions for a role
- `GET /auth/roles` - List all roles and permissions

### Items (`/items`)
- `POST /items/` - Create an item
- `GET /items/` - List items
- `GET /items/{item_id}` - Get an item
- `PUT /items/{item_id}` - Update an item
- `DELETE /items/{item_id}` - Delete an item

### Agent (`/agent`)
- `POST /agent/sessions` - Create a new agent session
- `GET /agent/sessions/{session_id}` - Get session state
- `POST /agent/sessions/{session_id}/plan` - Enter plan mode
- `POST /agent/sessions/{session_id}/execute-step` - Execute next step
- `POST /agent/sessions/{session_id}/execute-all` - Execute all steps
- `POST /agent/sessions/{session_id}/messages` - Add a message
- `POST /agent/sessions/{session_id}/archive` - Archive to cold storage

### MCP Server (`/mcp`)
- `GET /mcp/tools` - List available tools
- `GET /mcp/resources` - List available resources
- `POST /mcp/tools/call` - Call a tool
- `POST /mcp/resources/read` - Read a resource
- `POST /mcp/request` - Handle MCP protocol request
- `GET /mcp/capabilities` - Get server capabilities

## User Roles

| Role | Permissions |
|------|-------------|
| `admin` | Full access to all features |
| `user` | CRUD items, execute agent, MCP read/write |
| `read_only` | Read items, MCP read only |

## Checkpoint Storage

### Hot State (MongoDB)
- Active agent sessions
- User data
- Items data
- Real-time checkpoints

### Cold State (Redis)
- Archived sessions
- Token blacklist
- Session cache
- TTL-based expiration

## Token Generation for MCP Server

Use the internal API to generate tokens for MCP server RBAC:

```bash
curl -X POST http://localhost:8000/auth/token/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "username": "api_user",
    "role": "user",
    "expires_minutes": 60
  }'
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB connection URL | `mongodb://localhost:27017` |
| `MONGODB_DATABASE` | MongoDB database name | `mcp_demo` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `REDIS_DB` | Redis database number | `0` |
| `JWT_SECRET_KEY` | JWT signing secret | (required) |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration | `30` |
| `OPENAI_API_KEY` | OpenAI API key (optional) | - |
| `APP_HOST` | Application host | `0.0.0.0` |
| `APP_PORT` | Application port | `8000` |
| `DEBUG` | Debug mode | `true` |

## License

MIT License