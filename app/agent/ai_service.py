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
from app.mcp.client import mcp_client, get_mcp_tools_description

logger = get_logger("ai_service")


def get_system_tools_description() -> str:
    """Get a description of all available system tools for the AI."""
    return """
## Available MCP Tools (Model Context Protocol)

You have access to the following tools via the MCP Server. Use these tools in your plans.
All operations go through the MCP Server which handles authorization.

### Item Management Tools
1. **create_item** - Create a new item in the database
   - Parameters: name (string, required), description (string), data (object)
   
2. **read_item** - Read/retrieve an item from the database
   - Parameters: item_id (string, required)

3. **update_item** - Update an existing item
   - Parameters: item_id (string, required), name (string), description (string), data (object)

4. **delete_item** - Delete an item from the database
   - Parameters: item_id (string, required)

5. **list_items** - List all items with pagination
   - Parameters: skip (integer, default 0), limit (integer, default 100)

### Search Tools
6. **search_items** - Search items by text query
   - Parameters: query (string, required), field (string: all|name|description|data), limit, offset

### Batch Operation Tools
7. **bulk_create** - Create multiple items at once
   - Parameters: items (array of {name, description, data})

8. **bulk_delete** - Delete multiple items by IDs
   - Parameters: item_ids (array of strings)

### Statistics & Report Tools
9. **get_statistics** - Get database statistics
   - Parameters: none

10. **generate_report** - Generate a report
    - Parameters: report_type (summary|detailed|activity), filters (object)

### User Tools
11. **get_user_profile** - Get current user's profile
    - Parameters: none

12. **update_user_profile** - Update user profile
    - Parameters: display_name, email, preferences

## System Capabilities
- MCP Server handles all tool execution with proper authorization
- MongoDB for data storage
- Redis for caching
- JWT-based authentication
- Real-time streaming via SSE
"""


async def get_dynamic_tools_description() -> str:
    """Get dynamic tools description from MCP server.
    
    This fetches the actual tools available from the external MCP server.
    Falls back to static description if MCP server is unavailable.
    """
    try:
        return await get_mcp_tools_description()
    except Exception as e:
        logger.warning(f"Could not fetch MCP tools, using static description: {e}")
        return get_system_tools_description()


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
    
    def _format_previous_results(self, previous_results: List[Dict[str, Any]]) -> str:
        """Format previous task results for inclusion in prompts."""
        if not previous_results:
            return "No previous results available yet."
        
        formatted = []
        for i, result in enumerate(previous_results):
            task_name = result.get("task_name", f"Task {i+1}")
            status = result.get("status", "unknown")
            output = result.get("output_data", {})
            result_text = result.get("result", "")
            
            formatted.append(f"""
### Result {i+1}: {task_name}
- Status: {status}
- Result: {result_text}
- Output Data: {json.dumps(output, indent=2) if output else 'N/A'}
""")
        
        return "\n".join(formatted)
    
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
        
        # Get system context (MCP tools only - no direct API knowledge)
        system_tools = get_system_tools_description()
        
        # NOTE: We do NOT pass permissions to AI - authorization happens at MCP tool execution level
        # The AI should create plans freely; the MCP server enforces permissions when tools are called
        
        # Build the planning prompt with MCP tools only
        prompt = f"""You are a planning agent for an AI-powered system. Create a detailed execution plan for the following goal.

{system_tools}

---

## Your Task

GOAL: {goal}

{"CONTEXT: " + json.dumps(context) if context else ""}

Create a JSON plan that uses the MCP tools available in this system. The plan should reference specific MCP tools (like create_item, read_item, list_items, search_items, etc.).

IMPORTANT: Do NOT worry about user permissions. Just create the best plan to accomplish the goal. Authorization is handled automatically by the MCP server when tools are executed.

Response format:
{{
    "analysis": "Brief analysis of the goal and which MCP tools will be needed",
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
                    "tool": "MCP tool name to use (if applicable)",
                    "tool_params": {{}}  // Parameters for the tool if applicable
                }}
            ],
            "reasoning": "Why this step is needed",
            "mcp_tools_used": ["list of MCP tool names used in this step"]
        }}
    ],
    "mcp_tools_summary": ["all MCP tools that will be used across the plan"],
    "estimated_complexity": "low|medium|high",
    "potential_challenges": ["challenge1", "challenge2"]
}}

Important rules:
1. ONLY use MCP tools (create_item, read_item, update_item, delete_item, list_items, search_items, bulk_create, bulk_delete, get_statistics, generate_report, get_user_profile)
2. Research tasks can run in parallel when they don't depend on each other
3. Data operations that modify the database should be sequential
4. Validation should always be the final step
5. Include 3-6 steps depending on complexity
6. Each step should have 2-4 sub-tasks
7. Be specific about which MCP tools each task will use
8. Do NOT check or mention user permissions - just plan the best approach

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
        """Execute a single task, calling MCP tools via the external MCP Server."""
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
        
        # List of all available MCP tools
        available_mcp_tools = [
            "create_item", "read_item", "update_item", "delete_item", "list_items",
            "search_items", "bulk_create", "bulk_delete", 
            "get_statistics", "generate_report",
            "get_user_profile", "update_user_profile"
        ]
        
        # If a specific MCP tool is specified AND we have a token, execute via MCP client
        if task_tool and token and task_tool in available_mcp_tools:
            # Log MCP tool call with grepable prefix
            print(f"\n[MCP_CALL] ========== MCP TOOL CALL ==========")
            print(f"[MCP_CALL] Tool: {task_tool}")
            print(f"[MCP_CALL] Params: {json.dumps(task_tool_params, indent=2)}")
            print(f"[MCP_CALL] Session: {session_id}")
            print(f"[MCP_CALL] ======================================\n")
            
            log.info(f"🔧 Executing MCP tool via MCP Server: {task_tool}", data={"params": task_tool_params})
            
            try:
                # Call tool via MCP client (external MCP server)
                mcp_result = await mcp_client.call_tool(task_tool, task_tool_params, token)
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Log MCP result with grepable prefix
                print(f"\n[MCP_RESULT] ========== MCP TOOL RESULT ==========")
                print(f"[MCP_RESULT] Tool: {task_tool}")
                print(f"[MCP_RESULT] Duration: {duration_ms}ms")
                print(f"[MCP_RESULT] Result: {json.dumps(mcp_result, indent=2, default=str)[:2000]}")
                print(f"[MCP_RESULT] =========================================\n")
                
                # Check if result indicates error (dict with error key)
                if isinstance(mcp_result, dict) and mcp_result.get("error"):
                    log.error(f"❌ MCP tool {task_tool} failed: {mcp_result.get('error')}")
                    return {
                        "task_name": task_name,
                        "status": "failed",
                        "result": f"MCP tool error: {mcp_result.get('error')}",
                        "output_data": {"error": mcp_result.get("error")},
                        "duration_ms": duration_ms
                    }
                
                # Check if result contains authorization error as string
                result_str = str(mcp_result.get("result", "") if isinstance(mcp_result, dict) else mcp_result)
                if "Authorization error" in result_str or "Forbidden" in result_str or "insufficient permissions" in result_str:
                    log.error(f"❌ MCP tool {task_tool} authorization denied: {result_str}")
                    return {
                        "task_name": task_name,
                        "status": "authorization_failed",
                        "result": f"Authorization denied: {result_str}",
                        "output_data": {"error": result_str, "error_type": "authorization"},
                        "mcp_tool_executed": task_tool,
                        "notes": "Operation requires elevated permissions",
                        "duration_ms": duration_ms
                    }
                
                # Check for other tool execution failures in result
                if "Tool execution failed" in result_str or "error" in result_str.lower()[:50]:
                    log.error(f"❌ MCP tool {task_tool} execution failed: {result_str[:200]}")
                    return {
                        "task_name": task_name,
                        "status": "failed",
                        "result": f"Tool execution failed: {result_str[:200]}",
                        "output_data": {"error": result_str},
                        "mcp_tool_executed": task_tool,
                        "duration_ms": duration_ms
                    }
                
                log.info(f"✅ MCP tool {task_tool} succeeded", data={"result": str(mcp_result)[:200]})
                return {
                    "task_name": task_name,
                    "status": "success",
                    "result": f"Successfully executed {task_tool}",
                    "output_data": mcp_result if isinstance(mcp_result, dict) else {"result": mcp_result},
                    "mcp_tool_executed": task_tool,
                    "notes": "",
                    "duration_ms": duration_ms
                }
            except PermissionError as e:
                duration_ms = int((time.time() - start_time) * 1000)
                log.error(f"❌ MCP authorization error: {e}")
                return {
                    "task_name": task_name,
                    "status": "failed",
                    "result": f"Authorization error: {str(e)}",
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

## PREVIOUS TASK RESULTS (USE THIS DATA!)
{self._format_previous_results(context.get('previous_results', []))}

ADDITIONAL CONTEXT:
Goal: {context.get('goal', '')}
Tool: {context.get('tool', 'N/A')}
Tool Params: {json.dumps(context.get('tool_params', {}))}

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
