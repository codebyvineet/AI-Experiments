"""Multi-agent orchestrator with parallel and sequential execution."""

import uuid
import asyncio
import time
from typing import Dict, Any, List, Optional, Callable, AsyncGenerator
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field

from app.checkpoints import mongodb_checkpoint, redis_checkpoint
from app.models import AgentState
from app.config.logging_config import get_logger, LogContext
from app.agent.ai_service import ai_service

logger = get_logger("multi_agent")


class AgentType(str, Enum):
    """Types of agents in the system."""
    RESEARCH = "research"
    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"


class ExecutionMode(str, Enum):
    """Execution modes for agents."""
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


@dataclass
class AgentTask:
    """A task for an agent to execute."""
    task_id: str
    agent_type: AgentType
    description: str
    input_data: Dict[str, Any]
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class MultiAgentSession:
    """Session state for multi-agent orchestration."""
    session_id: str
    user_id: str
    goal: str
    user_permissions: List[str] = field(default_factory=list)
    token: Optional[str] = None  # JWT token for MCP tool calls
    plan: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[AgentTask] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "initialized"  # initialized, planning, executing, completed, failed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MultiAgentOrchestrator:
    """
    Orchestrates multiple AI agents with support for:
    - Parallel execution (e.g., multiple research agents)
    - Sequential execution (planning → execution → validation)
    - Real-time streaming of results
    - Plan modification by user
    - Real AI-powered planning and execution via Vertex AI
    """
    
    def __init__(self):
        self.sessions: Dict[str, MultiAgentSession] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.execution_results: Dict[str, List[Dict[str, Any]]] = {}
    
    async def create_session(self, user_id: str, goal: str, user_permissions: Optional[List[str]] = None, token: Optional[str] = None) -> MultiAgentSession:
        """Create a new multi-agent session."""
        log = LogContext(logger, user_id=user_id)
        
        session_id = str(uuid.uuid4())
        log.info(f"📦 Creating new session", data={
            "session_id": session_id, 
            "goal": goal,
            "permissions": user_permissions
        })
        
        session = MultiAgentSession(
            session_id=session_id,
            user_id=user_id,
            goal=goal,
            user_permissions=user_permissions or [],
            token=token  # Store token for MCP tool calls
        )
        self.sessions[session_id] = session
        self.execution_results[session_id] = []
        
        # Save to MongoDB
        await self._save_session_state(session)
        
        log.info(f"✅ Session created successfully", data={"session_id": session_id})
        return session
    
    async def _save_session_state(self, session: MultiAgentSession) -> None:
        """Save session state to MongoDB."""
        state = AgentState(
            session_id=session.session_id,
            user_id=session.user_id,
            state_type="hot",
            state_data={
                "goal": session.goal,
                "plan": session.plan,
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "agent_type": t.agent_type.value,
                        "description": t.description,
                        "input_data": t.input_data,
                        "status": t.status,
                        "result": t.result,
                        "error": t.error,
                        "started_at": t.started_at.isoformat() if t.started_at else None,
                        "completed_at": t.completed_at.isoformat() if t.completed_at else None
                    }
                    for t in session.tasks
                ],
                "messages": session.messages,
                "status": session.status
            },
            plan=session.plan,
            current_step=0,
            is_complete=session.status == "completed"
        )
        await mongodb_checkpoint.save_checkpoint(state)
    
    async def generate_plan(
        self, 
        session_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Generate a plan with streaming updates using real AI."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        log = LogContext(logger, session_id=session_id, user_id=session.user_id, agent_type="planning")
        log.info(f"🎯 Starting plan generation", data={"goal": session.goal})
        
        start_time = time.time()
        session.status = "planning"
        session.updated_at = datetime.now(timezone.utc)
        
        yield {
            "type": "status",
            "status": "planning",
            "message": "Starting AI-powered plan generation..."
        }
        
        # Use real AI to generate plan with tool awareness
        plan_steps = []
        try:
            log.info("🤖 Invoking AI planning agent with system tool context...")
            
            async for event in ai_service.generate_plan(
                goal=session.goal,
                session_id=session_id,
                context={"user_id": session.user_id, "messages": session.messages[-5:]},
                user_permissions=session.user_permissions
            ):
                if event["type"] == "plan_step":
                    plan_steps.append(event["step"])
                    session.plan.append(event["step"])
                    log.info(f"📍 Plan step {event['step_number']} generated", data={
                        "description": event["step"]["description"],
                        "phase": event["step"].get("phase"),
                        "mode": event["step"].get("execution_mode")
                    })
                yield event
            
            session.status = "planned"
            session.updated_at = datetime.now(timezone.utc)
            await self._save_session_state(session)
            
            duration_ms = int((time.time() - start_time) * 1000)
            log.info(f"✅ Plan generation complete", data={
                "total_steps": len(plan_steps),
                "duration_ms": duration_ms
            })
            
        except Exception as e:
            log.error(f"❌ Plan generation failed: {e}")
            # Fall back to rule-based plan if AI fails
            log.info("⚠️ Falling back to rule-based planning...")
            plan_steps = await self._create_plan_for_goal(session.goal)
            
            for i, step in enumerate(plan_steps):
                yield {
                    "type": "plan_step",
                    "step_number": i + 1,
                    "total_steps": len(plan_steps),
                    "step": step
                }
                session.plan.append(step)
            
            session.status = "planned"
            session.updated_at = datetime.now(timezone.utc)
            await self._save_session_state(session)
            
            yield {
                "type": "plan_complete",
                "plan": session.plan,
                "total_steps": len(session.plan),
                "message": "Plan generated (fallback mode). You can modify it or proceed with execution."
            }
    
    async def _create_plan_for_goal(self, goal: str) -> List[Dict[str, Any]]:
        """Create a detailed plan based on the goal."""
        goal_lower = goal.lower()
        steps = []
        
        # Phase 1: Research (can be parallel)
        if any(word in goal_lower for word in ["find", "search", "research", "look"]):
            steps.append({
                "step_id": str(uuid.uuid4()),
                "phase": "research",
                "description": "Search for relevant information",
                "agent_type": "research",
                "execution_mode": "parallel",
                "sub_tasks": [
                    {"name": "Search databases", "status": "pending"},
                    {"name": "Query external APIs", "status": "pending"},
                    {"name": "Analyze existing data", "status": "pending"}
                ],
                "status": "pending",
                "editable": True
            })
        
        # Phase 2: Analysis
        steps.append({
            "step_id": str(uuid.uuid4()),
            "phase": "analysis",
            "description": "Analyze gathered information",
            "agent_type": "research",
            "execution_mode": "sequential",
            "sub_tasks": [
                {"name": "Process raw data", "status": "pending"},
                {"name": "Extract insights", "status": "pending"}
            ],
            "status": "pending",
            "editable": True
        })
        
        # Phase 3: Execution
        if any(word in goal_lower for word in ["create", "make", "build", "generate"]):
            steps.append({
                "step_id": str(uuid.uuid4()),
                "phase": "execution",
                "description": "Execute the main task",
                "agent_type": "execution",
                "execution_mode": "sequential",
                "sub_tasks": [
                    {"name": "Prepare resources", "status": "pending"},
                    {"name": "Execute main action", "status": "pending"},
                    {"name": "Post-process results", "status": "pending"}
                ],
                "status": "pending",
                "editable": True
            })
        
        # Phase 4: Data operations (if needed)
        if any(word in goal_lower for word in ["store", "save", "update", "delete", "user", "item"]):
            steps.append({
                "step_id": str(uuid.uuid4()),
                "phase": "data_operations",
                "description": "Perform database operations via MCP",
                "agent_type": "execution",
                "execution_mode": "sequential",
                "sub_tasks": [
                    {"name": "Validate data", "status": "pending"},
                    {"name": "Execute MCP operations", "status": "pending"},
                    {"name": "Verify results", "status": "pending"}
                ],
                "status": "pending",
                "editable": True
            })
        
        # Phase 5: Validation
        steps.append({
            "step_id": str(uuid.uuid4()),
            "phase": "validation",
            "description": "Validate results and generate summary",
            "agent_type": "validation",
            "execution_mode": "sequential",
            "sub_tasks": [
                {"name": "Verify outputs", "status": "pending"},
                {"name": "Generate summary", "status": "pending"}
            ],
            "status": "pending",
            "editable": True
        })
        
        return steps
    
    async def update_plan(
        self, 
        session_id: str, 
        updated_plan: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Allow user to modify the plan."""
        log = LogContext(logger, session_id=session_id)
        
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        log.info(f"📝 Updating plan", data={
            "previous_steps": len(session.plan),
            "new_steps": len(updated_plan)
        })
        
        session.plan = updated_plan
        session.updated_at = datetime.now(timezone.utc)
        await self._save_session_state(session)
        
        log.info(f"✅ Plan updated successfully")
        return {
            "session_id": session_id,
            "status": "plan_updated",
            "plan": session.plan
        }
    
    async def execute_plan(
        self, 
        session_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute the plan with real AI agents and streaming updates."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        log = LogContext(logger, session_id=session_id, user_id=session.user_id)
        log.info(f"🚀 Starting plan execution", data={
            "goal": session.goal,
            "total_steps": len(session.plan)
        })
        
        execution_start = time.time()
        session.status = "executing"
        session.updated_at = datetime.now(timezone.utc)
        
        yield {
            "type": "status",
            "status": "executing",
            "message": "Starting AI-powered plan execution..."
        }
        
        step_results = []
        
        for step_index, step in enumerate(session.plan):
            step_start = time.time()
            step["status"] = "running"
            
            log.step_start(step_index + 1, step['description'], step.get('execution_mode', 'sequential'))
            
            yield {
                "type": "step_start",
                "step_index": step_index,
                "step": step,
                "message": f"Starting: {step['description']}"
            }
            
            # Execute based on mode using real AI
            task_results = []
            if step.get("execution_mode") == "parallel":
                async for update in self._execute_parallel_tasks_ai(step, session_id, session.goal, session, step_results):
                    if update.get("type") == "task_complete" and "result" in update:
                        task_results.append(update.get("result", {}))
                    yield update
            else:
                async for update in self._execute_sequential_tasks_ai(step, session_id, session.goal, session, step_results):
                    if update.get("type") == "task_complete" and "result" in update:
                        task_results.append(update.get("result", {}))
                    yield update
            
            step["status"] = "completed"
            step_duration = int((time.time() - step_start) * 1000)
            
            step_results.append({
                "step_index": step_index,
                "description": step["description"],
                "task_results": task_results,
                "duration_ms": step_duration
            })
            
            log.step_complete(step_index + 1, step_duration)
            
            yield {
                "type": "step_complete",
                "step_index": step_index,
                "step": step,
                "duration_ms": step_duration,
                "message": f"Completed: {step['description']}"
            }
            
            await self._save_session_state(session)
        
        session.status = "completed"
        session.updated_at = datetime.now(timezone.utc)
        await self._save_session_state(session)
        
        # Generate AI summary
        total_duration = int((time.time() - execution_start) * 1000)
        log.info(f"📊 Generating execution summary...")
        
        summary = await ai_service.generate_summary(
            session_id=session_id,
            goal=session.goal,
            executed_steps=session.plan,
            results=step_results
        )
        summary["total_duration_ms"] = total_duration
        
        log.info(f"✅ Plan execution complete", data={
            "total_steps": len(session.plan),
            "total_duration_ms": total_duration,
            "status": summary.get("overall_status", "success")
        })
        
        yield {
            "type": "execution_complete",
            "status": "completed",
            "message": "All steps completed successfully!",
            "summary": summary
        }
    
    async def _execute_parallel_tasks_ai(
        self, 
        step: Dict[str, Any],
        session_id: str,
        goal: str,
        session: MultiAgentSession,
        prior_step_results: List[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute sub-tasks in parallel using real AI."""
        log = LogContext(logger, session_id=session_id, phase=step.get("phase", "unknown"))
        
        sub_tasks = step.get("sub_tasks", [])
        prior_step_results = prior_step_results or []
        
        # Collect results from prior steps
        all_prior_results = []
        for prior_step in prior_step_results:
            for task_result in prior_step.get("task_results", []):
                all_prior_results.append(task_result)
        
        log.info(f"⚡ Starting parallel execution", data={
            "step": step["description"],
            "task_count": len(sub_tasks),
            "prior_results": len(all_prior_results)
        })
        
        yield {
            "type": "parallel_start",
            "step_id": step["step_id"],
            "task_count": len(sub_tasks),
            "message": f"Starting {len(sub_tasks)} parallel AI tasks..."
        }
        
        # Track if any task had auth failure
        auth_failure = None
        
        # Execute tasks in parallel using real AI
        async def execute_task_with_ai(task: Dict[str, Any], index: int):
            task_start = time.time()
            task["status"] = "running"
            
            log.info(f"🔄 Starting parallel task {index + 1}: {task['name']}")
            
            result = await ai_service.execute_task(
                task_name=task["name"],
                task_description=task.get("description", task["name"]),
                context={
                    "goal": goal, 
                    "step": step["description"],
                    "previous_results": all_prior_results[-5:] if all_prior_results else [],
                    "tool": task.get("tool"),
                    "tool_params": task.get("tool_params", {})
                },
                session_id=session_id,
                step_info=step,
                token=session.token  # Pass token for MCP calls
            )
            
            # Check for authorization failure
            if result.get("status") == "authorization_failed":
                task["status"] = "authorization_failed"
                task["result"] = result.get("result", "Authorization denied")
            else:
                task["status"] = "completed" if result.get("status") == "success" else result.get("status", "completed")
                task["result"] = result.get("result", "Completed")
            
            return {
                "index": index,
                "task": task,
                "result": result,
                "duration_ms": int((time.time() - task_start) * 1000)
            }
        
        # Run all tasks concurrently
        tasks_coro = [execute_task_with_ai(task, i) for i, task in enumerate(sub_tasks)]
        
        for completed in asyncio.as_completed(tasks_coro):
            result = await completed
            
            log.info(f"✓ Parallel task completed: {result['task']['name']}", data={
                "duration_ms": result["duration_ms"],
                "status": result["result"].get("status", "success")
            })
            
            yield {
                "type": "task_complete",
                "step_id": step["step_id"],
                "task": result["task"],
                "result": result["result"],
                "duration_ms": result["duration_ms"],
                "message": f"Completed: {result['task']['name']}"
            }
            
            # Track authorization failure
            if result["result"].get("status") == "authorization_failed":
                auth_failure = result
        
        # If any task had auth failure, stop execution
        if auth_failure:
            log.error(f"🚫 Authorization failure in parallel step - stopping execution")
            yield {
                "type": "execution_stopped",
                "reason": "authorization_failed",
                "message": f"Execution stopped: {auth_failure['result'].get('result', 'Insufficient permissions')}",
                "failed_task": auth_failure['task']['name']
            }
            return  # Stop further execution
        
        log.info(f"✅ All parallel tasks completed")
        
        yield {
            "type": "parallel_complete",
            "step_id": step["step_id"],
            "message": "All parallel tasks completed"
        }
    
    async def _execute_sequential_tasks_ai(
        self, 
        step: Dict[str, Any],
        session_id: str,
        goal: str,
        session: MultiAgentSession,
        prior_step_results: List[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute sub-tasks sequentially using real AI."""
        log = LogContext(logger, session_id=session_id, phase=step.get("phase", "unknown"))
        
        sub_tasks = step.get("sub_tasks", [])
        prior_step_results = prior_step_results or []
        
        log.info(f"📋 Starting sequential execution", data={
            "step": step["description"],
            "task_count": len(sub_tasks),
            "prior_steps": len(prior_step_results)
        })
        
        # Collect results from prior steps to pass as context
        all_prior_results = []
        for prior_step in prior_step_results:
            for task_result in prior_step.get("task_results", []):
                all_prior_results.append(task_result)
        
        # Start with results from prior steps
        previous_results = all_prior_results[-5:] if all_prior_results else []
        
        for i, task in enumerate(sub_tasks):
            task_start = time.time()
            task["status"] = "running"
            
            log.info(f"🔄 Starting sequential task {i + 1}/{len(sub_tasks)}: {task['name']}")
            
            yield {
                "type": "task_start",
                "step_id": step["step_id"],
                "task_index": i,
                "task": task,
                "message": f"Running: {task['name']}"
            }
            
            # Execute with AI, including context from previous tasks
            result = await ai_service.execute_task(
                task_name=task["name"],
                task_description=task.get("description", task["name"]),
                context={
                    "goal": goal, 
                    "step": step["description"],
                    "previous_results": previous_results[-3:] if previous_results else [],
                    "tool": task.get("tool"),
                    "tool_params": task.get("tool_params", {})
                },
                session_id=session_id,
                step_info=step,
                token=session.token  # Pass token for MCP calls
            )
            
            # Check for authorization failure - stop execution
            if result.get("status") == "authorization_failed":
                task["status"] = "authorization_failed"
                task["result"] = result.get("result", "Authorization denied")
                
                log.error(f"🚫 Authorization failure - stopping execution: {task['name']}")
                
                yield {
                    "type": "task_complete",
                    "step_id": step["step_id"],
                    "task_index": i,
                    "task": task,
                    "result": result,
                    "duration_ms": int((time.time() - task_start) * 1000),
                    "message": f"Authorization failed: {task['name']}"
                }
                
                yield {
                    "type": "execution_stopped",
                    "reason": "authorization_failed",
                    "message": f"Execution stopped: {result.get('result', 'Insufficient permissions')}",
                    "failed_task": task["name"]
                }
                return  # Stop further execution
            
            task["status"] = "completed" if result.get("status") == "success" else result.get("status", "completed")
            task["result"] = result.get("result", "Completed")
            previous_results.append(result)
            
            duration_ms = int((time.time() - task_start) * 1000)
            
            log.info(f"✓ Sequential task completed: {task['name']}", data={
                "duration_ms": duration_ms,
                "status": result.get("status", "success")
            })
            
            yield {
                "type": "task_complete",
                "step_id": step["step_id"],
                "task_index": i,
                "task": task,
                "result": result,
                "duration_ms": duration_ms,
                "message": f"Completed: {task['name']}"
            }
        
        log.info(f"✅ All sequential tasks completed")
    
    async def _generate_summary(self, session: MultiAgentSession) -> Dict[str, Any]:
        """Generate execution summary (fallback method)."""
        log = LogContext(logger, session_id=session.session_id)
        log.info("📊 Generating basic summary (fallback)")
        
        completed_steps = sum(1 for s in session.plan if s.get("status") == "completed")
        total_tasks = sum(len(s.get("sub_tasks", [])) for s in session.plan)
        
        return {
            "goal": session.goal,
            "total_steps": len(session.plan),
            "completed_steps": completed_steps,
            "total_tasks": total_tasks,
            "agents_used": list(set(s.get("agent_type", "unknown") for s in session.plan))
        }
    
    async def add_message(
        self, 
        session_id: str, 
        role: str, 
        content: str
    ) -> Dict[str, Any]:
        """Add a message to the session."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        session.messages.append(message)
        session.updated_at = datetime.now(timezone.utc)
        
        await self._save_session_state(session)
        
        return message
    
    async def get_session(self, session_id: str) -> Optional[MultiAgentSession]:
        """Get session by ID."""
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # Try to load from MongoDB
        state = await mongodb_checkpoint.get_checkpoint(session_id)
        if state:
            session = MultiAgentSession(
                session_id=state.session_id,
                user_id=state.user_id,
                goal=state.state_data.get("goal", ""),
                plan=state.state_data.get("plan", []),
                messages=state.state_data.get("messages", []),
                status=state.state_data.get("status", "initialized")
            )
            self.sessions[session_id] = session
            return session
        
        return None
    
    def get_all_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        return [
            {
                "session_id": s.session_id,
                "goal": s.goal,
                "status": s.status,
                "step_count": len(s.plan),
                "created_at": s.created_at.isoformat()
            }
            for s in self.sessions.values()
            if s.user_id == user_id
        ]


# Global instance
multi_agent_orchestrator = MultiAgentOrchestrator()
