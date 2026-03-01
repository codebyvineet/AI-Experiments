# AI-Experiments

A containerized Python application demonstrating MCP Server, LangGraph agent with plan mode, and JWT-based RBAC authentication. Powered by **Google Vertex AI with Gemini 2.5**.

## Features

- **MCP Server**: Model Context Protocol server with tools and resources
- **LangGraph Agent**: Agentic system with plan mode for multi-step task execution
- **Google Vertex AI**: Gemini 2.5 model integration for AI capabilities
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
│              Google Vertex AI (Gemini 2.5)                   │
├─────────────────────────────────────────────────────────────┤
│    MongoDB (Hot State)    │    Redis (Cold State)           │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

1. **Google Cloud Project** with Vertex AI API enabled
2. **Service Account** with Vertex AI permissions
3. **Docker** and **Docker Compose** installed

### Setting Up Google Cloud Credentials

1. Create a service account in Google Cloud Console
2. Grant the service account the following roles:
   - `Vertex AI User` (roles/aiplatform.user)
   - `Vertex AI Service Agent` (roles/aiplatform.serviceAgent) 
3. Download the service account JSON key file
4. Create a `credentials` directory in the project root:
   ```bash
   mkdir credentials
   ```
5. Place your service account JSON file in the credentials directory:
   ```bash
   mv /path/to/your-service-account.json credentials/service-account.json
   ```

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

3. Configure the `.env` file:
```bash
# Generate a secure JWT secret key
python -c 'import secrets; print(secrets.token_urlsafe(32))'

# Update .env with your values:
# - JWT_SECRET_KEY: paste the generated key
# - GOOGLE_CLOUD_PROJECT: your GCP project ID
# - GOOGLE_CLOUD_LOCATION: your preferred region (default: us-central1)
```

4. Set up credentials (see "Setting Up Google Cloud Credentials" above)

5. Start the application:
```bash
docker-compose up -d
```

6. Access the API documentation at `http://localhost:8000/docs`

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

3. Set up environment variables:
```bash
export JWT_SECRET_KEY="your-secret-key-at-least-32-chars"
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

4. Run the application:
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
| `JWT_SECRET_KEY` | JWT signing secret (min 32 chars) | (required) |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration | `30` |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project ID | (required for AI) |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI location | `us-central1` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | (required for AI) |
| `VERTEXAI_MODEL` | Vertex AI model name | `gemini-2.5-pro` |
| `APP_HOST` | Application host | `0.0.0.0` |
| `APP_PORT` | Application port | `8000` |
| `DEBUG` | Debug mode | `true` |

## License

MIT License