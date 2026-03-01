"""AI Service using Google Vertex AI for real agent operations."""

import json
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone

import vertexai
from vertexai.generative_models import GenerativeModel, Part, Content, Tool, FunctionDeclaration
from google.oauth2 import service_account

from app.config.settings import get_settings
from app.config.logging_config import get_logger, LogContext
from app.mcp.server import mcp_server

logger = get_logger("ai_service")


def get_system_tools_description() -> str:
    """Get a description of all available system tools for the AI."""
    return """
## Available MCP Tools (Model Context Protocol)

You have access to the following tools via the MCP Server. Use these in your plans:

### Item Management Tools
1. **create_item** - Create a new item in the database
   - Parameters: name (string, required), description (string), data (object)
   - Permission: items:write
   
2. **read_item** - Read/retrieve an item from the database
   - Parameters: item_id (string, required)
   - Permission: items:read

3. **update_item** - Update an existing item
   - Parameters: item_id (string, required), updates (object, required)
   - Permission: items:write

4. **delete_item** - Delete an item from the database
   - Parameters: item_id (string, required)
   - Permission: items:delete

### Agent Tools
5. **execute_agent** - Execute an AI agent task
   - Parameters: session_id (string, required), action (string, required)
   - Permission: agent:execute

### User Management Tools (Admin only)
6. **manage_users** - Manage system users
   - Parameters: action (string, required), user_data (object)
   - Permission: users:write

## Available Resources
- **items** (mcp://items) - Collection of all items in the system
- **users** (mcp://users) - User management resource
- **agent_sessions** (mcp://agent/sessions) - AI agent session data

## System Capabilities
- MongoDB for hot state storage (active sessions, items, users)
- Redis for cold state storage (archived checkpoints, cache)
- JWT-based authentication with role-based access control
- Real-time streaming via Server-Sent Events (SSE)

## User Roles & Permissions
- **admin**: Full access to all tools and resources
- **user**: Can read/write/delete items, execute agents, read/write MCP
- **read_only**: Can only read items and MCP resources
"""


def get_api_endpoints_description() -> str:
    """Get a description of available API endpoints."""
    return """
## Available REST API Endpoints

### Authentication (/auth)
- POST /auth/register - Register new user
- POST /auth/login - Login and get JWT token
- GET /auth/me - Get current user info
- POST /auth/token/internal - Generate internal API token

### Items CRUD (/items)
- GET /items/ - List all items
- POST /items/ - Create new item
- GET /items/{id} - Get specific item
- PUT /items/{id} - Update item
- DELETE /items/{id} - Delete item

### Agent Operations (/agent)
- POST /agent/sessions - Create agent session
- GET /agent/sessions - List sessions
- POST /agent/sessions/{id}/execute - Execute session

### MCP Server (/mcp)
- GET /mcp/tools - List available MCP tools
- POST /mcp/call/{tool_name} - Call an MCP tool
- GET /mcp/resources - List available resources

### Streaming (/stream)
- POST /stream/sessions - Create streaming session
- GET /stream/sessions/{id}/plan - Stream plan generation
- GET /stream/sessions/{id}/execute - Stream plan execution
"""


class AIService:
    """Service for interacting with Google Vertex AI Gemini models."""
    
    def __init__(self):
        self.settings = get_settings()
        self.model: Optional[GenerativeModel] = None
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Initialize the Vertex AI client."""
        log = LogContext(logger)
        
        if self._initialized:
            return True
        
        try:
            log.info("🔧 Initializing Vertex AI client", data={
                "project": self.settings.google_cloud_project,
                "location": self.settings.google_cloud_location,
                "model": self.settings.vertexai_model
            })
            
            # Initialize Vertex AI
            if self.settings.google_application_credentials:
                credentials = service_account.Credentials.from_service_account_file(
                    self.settings.google_application_credentials
                )
                vertexai.init(
                    project=self.settings.google_cloud_project,
                    location=self.settings.google_cloud_location,
                    credentials=credentials
                )
            else:
                vertexai.init(
                    project=self.settings.google_cloud_project,
                    location=self.settings.google_cloud_location
                )
            
            # Create model instance
            self.model = GenerativeModel(self.settings.vertexai_model)
            self._initialized = True
            log.info("✅ Vertex AI client initialized successfully")
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to initialize Vertex AI: {e}")
            return False
    
    async def generate_plan(
        self, 
        goal: str, 
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        user_permissions: Optional[List[str]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Generate a structured plan using AI with awareness of available tools."""
        log = LogContext(logger, session_id=session_id, agent_type="planning")
        
        if not self._initialized:
            await self.initialize()
        
        log.info(f"📋 Generating plan for goal: {goal}")
        log.info(f"🔧 User permissions: {user_permissions or 'not specified'}")
        
        # Get system context (tools, APIs, capabilities)
        system_tools = get_system_tools_description()
        api_endpoints = get_api_endpoints_description()
        
        # Filter tools based on user permissions if provided
        permission_context = ""
        if user_permissions:
            permission_context = f"""
## Your Available Permissions
You have the following permissions: {', '.join(user_permissions)}

Only use tools and resources that match your permissions. For example:
- items:read allows read_item and listing items
- items:write allows create_item and update_item
- items:delete allows delete_item
- agent:execute allows execute_agent
- mcp:read/write allows MCP operations
"""
        
        # Build the planning prompt with full system context
        prompt = f"""You are a planning agent for an AI-powered system. Create a detailed execution plan for the following goal.

{system_tools}

{api_endpoints}

{permission_context}

---

## Your Task

GOAL: {goal}

{"CONTEXT: " + json.dumps(context) if context else ""}

Create a JSON plan that uses the ACTUAL tools and APIs available in this system. The plan should reference specific MCP tools (like create_item, read_item, etc.) and API endpoints where appropriate.

Response format:
{{
    "analysis": "Brief analysis of the goal and which tools/APIs will be needed",
    "steps": [
        {{
            "phase": "research|analysis|execution|data_operations|validation",
            "description": "What this step does",
            "agent_type": "research|execution|validation",
            "execution_mode": "parallel|sequential",
            "sub_tasks": [
                {{
                    "name": "Task name",
                    "description": "Task details",
                    "tool": "MCP tool name or API endpoint to use (if applicable)",
                    "tool_params": {{}}  // Parameters for the tool if applicable
                }}
            ],
            "reasoning": "Why this step is needed",
            "mcp_tools_used": ["list of MCP tool names used in this step"]
        }}
    ],
    "mcp_tools_summary": ["all MCP tools that will be used across the plan"],
    "api_endpoints_summary": ["all API endpoints that will be called"],
    "estimated_complexity": "low|medium|high",
    "potential_challenges": ["challenge1", "challenge2"]
}}

Important rules:
1. Reference ACTUAL tools from the system (create_item, read_item, update_item, delete_item, etc.)
2. Research tasks can run in parallel when they don't depend on each other
3. Data operations that modify the database should be sequential
4. Validation should always be the final step
5. Include 3-6 steps depending on complexity
6. Each step should have 2-4 sub-tasks
7. Be specific about which MCP tools or API endpoints each task will use

Respond ONLY with valid JSON, no markdown or explanation.
"""
        
        start_time = time.time()
        log.ai_request(prompt, self.settings.vertexai_model)
        
        try:
            # Generate response
            response = await self._generate_content(prompt, session_id)
            duration_ms = int((time.time() - start_time) * 1000)
            log.ai_response(response, duration_ms)
            
            # Parse the plan
            plan_data = json.loads(response)
            
            # Yield analysis first
            yield {
                "type": "thinking",
                "agent": "planning",
                "content": plan_data.get("analysis", "Analyzing goal...")
            }
            
            # Yield each step
            steps = plan_data.get("steps", [])
            for i, step in enumerate(steps):
                import uuid
                step["step_id"] = str(uuid.uuid4())
                step["status"] = "pending"
                step["editable"] = True
                
                # Add default sub_tasks if missing
                if "sub_tasks" not in step:
                    step["sub_tasks"] = [{"name": "Execute", "status": "pending"}]
                else:
                    for task in step["sub_tasks"]:
                        task["status"] = "pending"
                
                yield {
                    "type": "plan_step",
                    "step_number": i + 1,
                    "total_steps": len(steps),
                    "step": step,
                    "reasoning": step.get("reasoning", "")
                }
                
                log.info(f"📍 Generated step {i+1}: {step['description']}", data={
                    "phase": step.get("phase"),
                    "mode": step.get("execution_mode"),
                    "sub_tasks": len(step.get("sub_tasks", []))
                })
            
            # Yield completion
            yield {
                "type": "plan_complete",
                "plan": steps,
                "total_steps": len(steps),
                "complexity": plan_data.get("estimated_complexity", "medium"),
                "challenges": plan_data.get("potential_challenges", []),
                "message": "Plan generated by AI. You can modify it or proceed with execution."
            }
            
            log.info(f"✅ Plan generation complete", data={
                "total_steps": len(steps),
                "complexity": plan_data.get("estimated_complexity")
            }, duration_ms=duration_ms)
            
        except json.JSONDecodeError as e:
            log.error(f"❌ Failed to parse AI response as JSON: {e}")
            # Fall back to default plan
            yield {"type": "error", "error": f"AI response parsing error: {e}"}
        except Exception as e:
            log.error(f"❌ Plan generation failed: {e}")
            yield {"type": "error", "error": str(e)}
    
    async def execute_task(
        self,
        task_name: str,
        task_description: str,
        context: Dict[str, Any],
        session_id: str,
        step_info: Dict[str, Any],
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute a single task, directly calling MCP tools when specified."""
        log = LogContext(
            logger, 
            session_id=session_id, 
            agent_type=step_info.get("agent_type", "execution"),
            phase=step_info.get("phase", "unknown")
        )
        
        if not self._initialized:
            await self.initialize()
        
        log.agent_start(task_name, task_description)
        start_time = time.time()
        
        # Get tool information from the task if specified
        task_tool = context.get("tool") or step_info.get("tool")
        task_tool_params = context.get("tool_params") or step_info.get("tool_params", {})
        
        # If a specific MCP tool is specified AND we have a token, execute it directly
        if task_tool and token and task_tool in ["create_item", "read_item", "update_item", "delete_item", "list_items"]:
            log.info(f"🔧 Directly executing MCP tool: {task_tool}", data={"params": task_tool_params})
            
            try:
                mcp_result = await mcp_server.call_tool(token, task_tool, task_tool_params)
                duration_ms = int((time.time() - start_time) * 1000)
                
                if mcp_result.error:
                    log.error(f"❌ MCP tool {task_tool} failed: {mcp_result.error}")
                    return {
                        "task_name": task_name,
                        "status": "failed",
                        "result": f"MCP tool error: {mcp_result.error.get('message', 'Unknown error')}",
                        "output_data": {"error": mcp_result.error},
                        "duration_ms": duration_ms
                    }
                
                log.info(f"✅ MCP tool {task_tool} succeeded", data={"result": mcp_result.result})
                return {
                    "task_name": task_name,
                    "status": "success",
                    "result": f"Successfully executed {task_tool}",
                    "output_data": mcp_result.result or {},
                    "mcp_tool_executed": task_tool,
                    "notes": "",
                    "duration_ms": duration_ms
                }
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                log.error(f"❌ MCP tool execution error: {e}")
                return {
                    "task_name": task_name,
                    "status": "failed",
                    "result": f"MCP execution error: {str(e)}",
                    "duration_ms": duration_ms
                }
        
        # For non-MCP tasks or tasks without tools, use AI to process
        mcp_tools_used = step_info.get("mcp_tools_used", [])
        
        # Build context-aware prompt
        tool_context = ""
        if task_tool or mcp_tools_used:
            tool_context = f"""
## MCP Tool to Execute
Tool: {task_tool or mcp_tools_used}
Parameters: {json.dumps(task_tool_params)}

This is an informational task. The MCP tool will be executed separately.
"""
        
        prompt = f"""You are an execution agent performing a specific task in a system with MCP tools.

{get_system_tools_description()}

---

TASK: {task_name}
DESCRIPTION: {task_description}

{tool_context}

STEP CONTEXT:
- Phase: {step_info.get('phase', 'unknown')}
- Agent Type: {step_info.get('agent_type', 'execution')}
- Step Description: {step_info.get('description', '')}
- MCP Tools for this step: {mcp_tools_used}

ADDITIONAL CONTEXT:
{json.dumps(context, indent=2)}

Execute this task and provide a structured result:
{{
    "status": "success|partial|failed",
    "result": "Description of what was accomplished",
    "output_data": {{}},
    "notes": "Any observations or recommendations",
    "next_actions": []
}}

Respond ONLY with valid JSON.
"""
        
        log.ai_request(prompt, self.settings.vertexai_model)
        
        try:
            response = await self._generate_content(prompt, session_id)
            duration_ms = int((time.time() - start_time) * 1000)
            log.ai_response(response, duration_ms)
            
            result = json.loads(response)
            log.agent_complete(task_name, result.get("result", ""), duration_ms)
            
            return {
                "task_name": task_name,
                "status": result.get("status", "success"),
                "result": result.get("result", "Task completed"),
                "output_data": result.get("output_data", {}),
                "notes": result.get("notes", ""),
                "duration_ms": duration_ms
            }
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log.error(f"❌ Task execution failed: {e}", duration_ms=duration_ms)
            return {
                "task_name": task_name,
                "status": "failed",
                "result": f"Error: {str(e)}",
                "duration_ms": duration_ms
            }
    
    async def analyze_for_mcp(
        self,
        goal: str,
        available_tools: List[Dict[str, Any]],
        session_id: str
    ) -> Dict[str, Any]:
        """Analyze which MCP tools to use for a goal."""
        log = LogContext(logger, session_id=session_id, agent_type="mcp_analyzer")
        
        if not self._initialized:
            await self.initialize()
        
        log.info("🔍 Analyzing goal for MCP tool usage", data={"goal": goal, "available_tools": len(available_tools)})
        
        tools_desc = "\n".join([
            f"- {t['name']}: {t['description']}" 
            for t in available_tools
        ])
        
        prompt = f"""Analyze this goal and determine which MCP tools should be used.

GOAL: {goal}

AVAILABLE MCP TOOLS:
{tools_desc}

Provide a JSON response:
{{
    "tools_to_use": [
        {{
            "tool_name": "name",
            "reason": "why this tool is needed",
            "arguments": {{}},  // suggested arguments
            "order": 1  // execution order
        }}
    ],
    "analysis": "Brief explanation of the approach"
}}

Respond ONLY with valid JSON.
"""
        
        start_time = time.time()
        log.ai_request(prompt, self.settings.vertexai_model)
        
        try:
            response = await self._generate_content(prompt, session_id)
            duration_ms = int((time.time() - start_time) * 1000)
            log.ai_response(response, duration_ms)
            
            result = json.loads(response)
            log.info("✅ MCP analysis complete", data={
                "tools_recommended": len(result.get("tools_to_use", []))
            }, duration_ms=duration_ms)
            
            return result
            
        except Exception as e:
            log.error(f"❌ MCP analysis failed: {e}")
            return {"tools_to_use": [], "analysis": f"Error: {e}"}
    
    async def generate_summary(
        self,
        session_id: str,
        goal: str,
        executed_steps: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate an execution summary."""
        log = LogContext(logger, session_id=session_id, agent_type="summarizer")
        
        if not self._initialized:
            await self.initialize()
        
        log.info("📊 Generating execution summary")
        
        prompt = f"""Generate a summary of the completed execution.

ORIGINAL GOAL: {goal}

EXECUTED STEPS:
{json.dumps(executed_steps, indent=2)}

RESULTS:
{json.dumps(results, indent=2)}

Provide a JSON summary:
{{
    "overall_status": "success|partial|failed",
    "summary": "What was accomplished",
    "key_results": ["result1", "result2"],
    "recommendations": ["recommendation1"],
    "metrics": {{
        "steps_completed": N,
        "tasks_executed": N
    }}
}}

Respond ONLY with valid JSON.
"""
        
        start_time = time.time()
        log.ai_request(prompt, self.settings.vertexai_model)
        
        try:
            response = await self._generate_content(prompt, session_id)
            duration_ms = int((time.time() - start_time) * 1000)
            log.ai_response(response, duration_ms)
            
            return json.loads(response)
            
        except Exception as e:
            log.error(f"❌ Summary generation failed: {e}")
            return {
                "overall_status": "partial",
                "summary": f"Execution completed but summary generation failed: {e}",
                "key_results": [],
                "metrics": {"steps_completed": len(executed_steps)}
            }
    
    async def _generate_content(self, prompt: str, session_id: str) -> str:
        """Generate content using the model."""
        log = LogContext(logger, session_id=session_id)
        
        if not self.model:
            raise RuntimeError("AI model not initialized")
        
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            
            # Clean up response if wrapped in markdown
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            return text.strip()
            
        except Exception as e:
            log.error(f"❌ Content generation error: {e}")
            raise


# Global AI service instance
ai_service = AIService()
