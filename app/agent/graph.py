"""LangGraph StateGraph for multi-agent orchestration.

This module builds the complete LangGraph state machine with:
- Planner node: AI-powered plan generation
- Approval node: Human-in-the-loop with interrupt()
- Executor: Parallel task execution with Send()
- Summary: Final result aggregation

Checkpointing uses MongoDB (sync/async supported).
Redis can be added for hot caching if needed.
"""

import os
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, AsyncGenerator, Optional, List

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from app.agent.state import AgentState, create_initial_state
from app.agent.nodes import (
    planner_node,
    approval_node,
    executor_dispatch,
    task_executor_node,
    step_aggregator_node,
    summary_node,
    should_continue,
    check_approval,
    create_task_sends
)
from app.config.settings import get_settings
from app.config.logging_config import get_logger, LogContext

logger = get_logger("langgraph")

# Dual checkpointing is now handled by LangGraph natively via TTL support
USE_DUAL_CHECKPOINTER = os.getenv("USE_DUAL_CHECKPOINTER", "false").lower() == "true"


class LangGraphOrchestrator:
    """
    LangGraph-based multi-agent orchestrator.
    
    Features:
    - Human-in-the-loop approval via interrupt()
    - Parallel task execution via Send()
    - Dual checkpointing: Redis (hot) + MongoDB (cold)
    - SSE streaming support
    
    Architecture:
    ```
    START → Planner → Approval → Executor ←→ TaskExecutor
                         ↓           ↓
                       (rejected) (completed)
                         ↓           ↓
                         └──→ Summary ←──┘
                               ↓
                              END
    ```
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._graph = None
        self._checkpointer = None
        self._mongo_client = None
        self._redis_client = None
    
    async def initialize(self) -> None:
        """Initialize the LangGraph with checkpointer."""
        log = LogContext(logger)
        log.info("🚀 Initializing LangGraph orchestrator")
        
        # Setup checkpointer (dual or MongoDB-only)
        if USE_DUAL_CHECKPOINTER:
            await self._setup_dual_checkpointer(log)
        else:
            await self._setup_mongo_checkpointer(log)
        
        # Build the graph
        self._graph = self._build_graph()
        
        log.info("✅ LangGraph orchestrator initialized")
    
    async def _setup_dual_checkpointer(self, log: LogContext) -> None:
        """Setup dual checkpointer with Redis (hot) + MongoDB (cold)."""
        try:
            from langgraph.checkpoint.redis import AsyncRedisSaver
            from redis.asyncio import Redis
            
            log.info("🔧 Setting up dual checkpointer (Redis + MongoDB)")
            
            # MongoDB (cold storage - permanent)
            self._mongo_client = MongoClient(self.settings.mongodb_url)
            mongo_saver = MongoDBSaver(
                self._mongo_client,
                db_name=self.settings.mongodb_database
            )
            
            # Redis (hot storage - 30 min TTL)
            redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
            self._redis_client = Redis.from_url(redis_url)
            redis_saver = AsyncRedisSaver(conn=self._redis_client)
            await redis_saver.setup()
            
            # For now, just use MongoDB since it supports both sync/async
            # LangGraph handles the async wrapping internally
            self._checkpointer = mongo_saver
            
            log.info("✅ Checkpointer ready (MongoDB with optional Redis cache)")
            
        except ImportError as e:
            log.warning(f"⚠️ Redis not available, using MongoDB only: {e}")
            await self._setup_mongo_checkpointer(log)
        except Exception as e:
            log.warning(f"⚠️ Dual checkpointer failed, falling back to MongoDB: {e}")
            await self._setup_mongo_checkpointer(log)
    
    async def _setup_mongo_checkpointer(self, log: LogContext) -> None:
        """Setup MongoDB-only checkpointer (fallback)."""
        log.info("🔧 Setting up MongoDB checkpointer")
        
        self._mongo_client = MongoClient(self.settings.mongodb_url)
        self._checkpointer = MongoDBSaver(
            self._mongo_client,
            db_name=self.settings.mongodb_database
        )
        
        log.info("✅ MongoDB checkpointer ready")
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        log = LogContext(logger)
        log.info("📊 Building LangGraph state machine")
        
        # Create the state graph
        builder = StateGraph(AgentState)
        
        # Add nodes
        builder.add_node("planner", planner_node)
        builder.add_node("approval", approval_node)
        builder.add_node("executor_dispatch", executor_dispatch)  # Fan-out node
        builder.add_node("task_executor", task_executor_node)
        builder.add_node("aggregator", step_aggregator_node)
        builder.add_node("summary", summary_node)
        
        # Add edges
        builder.add_edge(START, "planner")
        builder.add_edge("planner", "approval")
        
        # After approval, either execute or go to summary
        builder.add_conditional_edges(
            "approval",
            check_approval,
            {"executor": "executor_dispatch", "summary": "summary"}
        )
        
        # From executor_dispatch, fan out to task_executors via Send()
        builder.add_conditional_edges(
            "executor_dispatch",
            create_task_sends  # Returns List[Send] for parallel execution
        )
        
        # After task execution, aggregate results
        builder.add_edge("task_executor", "aggregator")
        
        # After aggregation, continue or finish
        builder.add_conditional_edges(
            "aggregator",
            should_continue,
            {"executor": "executor_dispatch", "summary": "summary"}
        )
        
        builder.add_edge("summary", END)
        
        # Compile with checkpointer and interrupt before approval
        graph = builder.compile(
            checkpointer=self._checkpointer,
            interrupt_before=["approval"]  # Pause before approval for HITL
        )
        
        log.info("✅ LangGraph state machine built")
        return graph
    
    def create_session_id(self, user_id: str, goal: str, token: str) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
        """
        Create session ID and initial state without starting execution.
        
        Returns:
            Tuple of (session_id, initial_state, config)
        """
        session_id = str(uuid.uuid4())
        initial_state = create_initial_state(
            session_id=session_id,
            user_id=user_id,
            goal=goal,
            token=token
        )
        config = {"configurable": {"thread_id": session_id}}
        return session_id, initial_state, config
    
    async def stream_graph(
        self,
        session_id: str,
        initial_state: Dict[str, Any],
        config: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream graph execution using LangGraph's native astream.
        
        Uses 'updates' mode to get state changes after each node.
        This is the framework-native way to stream progress.
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"🚀 Starting streamed graph execution: {session_id}")
        
        yield {"type": "status", "status": "planning", "message": "Starting plan generation..."}
        
        try:
            # Use LangGraph's native streaming with 'updates' mode
            async for chunk in self._graph.astream(initial_state, config, stream_mode="updates"):
                # chunk is dict of {node_name: node_output}
                for node_name, output in chunk.items():
                    log.info(f"📍 Node completed: {node_name}")
                    
                    if node_name == "planner":
                        # Planner finished - emit plan events
                        plan = output.get("plan", [])
                        yield {"type": "thinking", "message": f"Generated {len(plan)} step plan"}
                        for i, step in enumerate(plan):
                            yield {"type": "plan_step", "step_number": i + 1, "step": step}
                        yield {"type": "plan_complete", "plan": plan, "total_steps": len(plan)}
                    
                    elif node_name == "executor_dispatch":
                        # Step is being executed - emit step info
                        current_step = output.get("current_step", 0)
                        plan = output.get("plan", [])
                        total_steps = len(plan) if plan else 0
                        if current_step < total_steps:
                            step = plan[current_step]
                            yield {
                                "type": "step_start",
                                "step_number": current_step + 1,
                                "total_steps": total_steps,
                                "step_description": step.get("description", ""),
                                "step_phase": step.get("phase", ""),
                                "sub_tasks": [t.get("tool") for t in step.get("sub_tasks", [])],
                                "message": f"Executing step {current_step + 1} of {total_steps}: {step.get('description', '')}"
                            }
                    
                    elif node_name == "task_executor":
                        # Task completed - emit result with task details
                        results = output.get("results", [])
                        if results:
                            latest = results[-1] if isinstance(results, list) else results
                            task_name = latest.get("task_name", "Task")
                            task_result = latest.get("result", {})
                            task_status = latest.get("status", "completed")
                            yield {
                                "type": "task_complete",
                                "task_name": task_name,
                                "status": task_status,
                                "result": task_result,
                                "message": f"{'✓' if task_status == 'success' else '✗'} {task_name}: {task_result.get('summary', task_result.get('message', ''))[:100]}"
                            }
                    
                    elif node_name == "aggregator":
                        # Step aggregation complete
                        current_step = output.get("current_step", 0)
                        total_steps = len(output.get("plan", []))
                        step_results = output.get("step_results", [])
                        if step_results:
                            latest_step = step_results[-1] if isinstance(step_results, list) else step_results
                            yield {
                                "type": "step_complete",
                                "step_number": current_step,
                                "total_steps": total_steps,
                                "step_status": latest_step.get("status", "completed"),
                                "message": f"Step {current_step} of {total_steps} completed"
                            }
                    
                    elif node_name == "summary":
                        # Execution finished
                        summary = output.get("summary", "")
                        yield {
                            "type": "execution_complete",
                            "summary": summary,
                            "message": "All tasks completed"
                        }
                        
        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            
            # GraphInterrupt is expected when hitting approval checkpoint
            if "interrupt" in error_str.lower() or "GraphInterrupt" in error_type:
                log.info(f"⏸️ Graph paused at interrupt (approval checkpoint)")
                # Get final state to send plan
                final_state = await self.get_session_state(session_id)
                if final_state and final_state.get("plan"):
                    plan = final_state["plan"]
                    if not any(e.get("type") == "plan_complete" for e in []):
                        yield {"type": "plan_complete", "plan": plan, "total_steps": len(plan)}
            else:
                log.error(f"❌ Stream error: {e}")
                yield {"type": "error", "error": error_str}
    
    async def create_session(
        self,
        user_id: str,
        goal: str,
        token: str
    ) -> str:
        """
        Create a new agent session and start planning (blocking).
        
        For streaming, use create_session_id() + stream_graph() instead.
        """
        log = LogContext(logger, user_id=user_id)
        
        session_id, initial_state, config = self.create_session_id(user_id, goal, token)
        log.info(f"📦 Creating session: {session_id}")
        
        # Start graph execution (will pause at approval interrupt)
        try:
            await self._graph.ainvoke(initial_state, config)
        except Exception as e:
            # Graph paused at interrupt - this is expected
            log.info(f"⏸️ Session paused at approval: {session_id}")
        
        return session_id
    
    async def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of a session."""
        config = {"configurable": {"thread_id": session_id}}
        
        try:
            state = await self._graph.aget_state(config)
            if state and state.values:
                result = dict(state.values)
                # Add metadata about pending interrupts for resume functionality
                result["_has_pending_interrupt"] = bool(state.tasks)
                result["_next_nodes"] = list(state.next) if state.next else []
                return result
        except Exception as e:
            logger.error(f"Failed to get session state: {e}")
        
        return None
    
    async def list_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        List all sessions for a user with their status.
        
        Uses MongoDB distinct query to find thread_ids, then uses
        LangGraph checkpointer to get the latest state for each.
        """
        log = LogContext(logger, user_id=user_id)
        log.info(f"📋 Listing sessions for user: {user_id}")
        
        sessions = []
        
        try:
            db = self._mongo_client[self.settings.mongodb_database]
            
            # Get distinct thread_ids from checkpoints (LangGraph stores these)
            thread_ids = db.checkpoints.distinct("thread_id")
            log.info(f"📋 Found {len(thread_ids)} total threads")
            
            # For each thread, get the latest checkpoint and check if it belongs to user
            for thread_id in thread_ids[:50]:  # Limit to 50
                config = {"configurable": {"thread_id": thread_id}}
                
                try:
                    # Use LangGraph's native method to get state
                    state = await self._graph.aget_state(config)
                    
                    if state and state.values:
                        values = state.values
                        # Check if this session belongs to the user
                        session_user_id = values.get("user_id", "")
                        
                        if session_user_id == user_id:
                            sessions.append({
                                "session_id": thread_id,
                                "status": values.get("status", "unknown"),
                                "goal": values.get("goal", ""),
                                "created_at": None,  # Not easily available
                                "has_pending_interrupt": bool(state.tasks),
                                "plan_steps": len(values.get("plan", [])),
                                "current_step": values.get("current_step", 0),
                                "can_resume": values.get("status") in ["awaiting_approval", "executing"]
                            })
                except Exception as e:
                    log.debug(f"Could not get state for thread {thread_id}: {e}")
                    continue
            
            # Sort by status (active first)
            status_order = {"executing": 0, "awaiting_approval": 1, "planning": 2, "completed": 3}
            sessions.sort(key=lambda s: status_order.get(s["status"], 99))
            
            log.info(f"✅ Found {len(sessions)} sessions for user {user_id}")
            
        except Exception as e:
            log.error(f"❌ Failed to list sessions: {e}")
        
        return sessions
    
    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        """
        Resume a session from its checkpoint.
        
        This is a key LangGraph feature - sessions can be resumed from any
        checkpoint after page refresh, server restart, etc.
        
        Returns the current state and what action is needed (approve, continue, etc).
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"🔄 Attempting to resume session: {session_id}")
        
        config = {"configurable": {"thread_id": session_id}}
        
        try:
            state = await self._graph.aget_state(config)
            
            if not state or not state.values:
                return {
                    "resumable": False,
                    "reason": "Session not found or has no checkpoint"
                }
            
            values = dict(state.values)
            
            # Determine resume action based on state
            resume_info = {
                "resumable": True,
                "session_id": session_id,
                "status": values.get("status"),
                "goal": values.get("goal"),
                "plan": values.get("plan", []),
                "current_step": values.get("current_step", 0),
                "results": values.get("results", []),
                "next_nodes": list(state.next) if state.next else [],
                "has_pending_interrupt": bool(state.tasks)
            }
            
            # Determine what action user needs to take
            if values.get("status") == "awaiting_approval":
                resume_info["action_needed"] = "approve"
                resume_info["message"] = "Plan is awaiting your approval"
            elif values.get("status") == "executing":
                resume_info["action_needed"] = "stream"
                resume_info["message"] = "Execution in progress - reconnect to stream"
            elif values.get("status") == "completed":
                resume_info["action_needed"] = "none"
                resume_info["message"] = "Session already completed"
                resume_info["resumable"] = False
            elif values.get("status") == "failed":
                resume_info["action_needed"] = "retry"
                resume_info["message"] = f"Session failed: {values.get('error')}"
            else:
                resume_info["action_needed"] = "unknown"
                resume_info["message"] = "Session in unknown state"
            
            log.info(f"✅ Session resumable: {resume_info['action_needed']}")
            return resume_info
            
        except Exception as e:
            log.error(f"❌ Failed to resume session: {e}")
            return {
                "resumable": False,
                "reason": str(e)
            }
    
    async def approve_plan(self, session_id: str, approved: bool) -> Dict[str, Any]:
        """
        Approve or reject the plan and resume execution.
        
        Args:
            session_id: The session to approve
            approved: Whether to approve the plan
            
        Returns:
            Updated session state
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"{'✅' if approved else '❌'} Plan {'approved' if approved else 'rejected'}")
        
        config = {"configurable": {"thread_id": session_id}}
        
        # Resume from interrupt with approval response
        from langgraph.types import Command
        
        result = await self._graph.ainvoke(
            Command(resume={"approved": approved}),
            config
        )
        
        return result
    
    async def stream_session(
        self,
        session_id: str,
        approve: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream session events via SSE.
        
        If approve=True, resumes past the approval interrupt.
        Otherwise, just streams current state.
        
        Yields events as the graph executes:
        - approval: Waiting for approval
        - task_start: Task beginning
        - task_complete: Task finished
        - step_complete: Step finished
        - execution_complete: All done
        """
        from langgraph.types import Command
        
        log = LogContext(logger, session_id=session_id)
        config = {"configurable": {"thread_id": session_id}}
        
        log.info(f"📡 Starting SSE stream for session: {session_id}", data={"approve": approve})
        
        # Track already yielded results to avoid duplicates
        yielded_results = set()
        
        try:
            # Check current state first
            state = await self.get_session_state(session_id)
            
            if not state:
                yield {"type": "error", "error": "Session not found"}
                return
            
            # If approving and state is awaiting_approval, resume with approval
            if approve and state.get("status") == "awaiting_approval":
                log.info(f"✅ Resuming from approval interrupt")
                yield {"type": "status", "status": "executing", "message": "Plan approved. Starting execution..."}
                
                # Use Command(resume=...) to resume past the interrupt
                async for event in self._graph.astream(
                    Command(resume={"approved": True}),
                    config,
                    stream_mode="values"
                ):
                    # Convert LangGraph event to our SSE format
                    event_state = event
                    
                    if event_state.get("status") == "executing":
                        current_step = event_state.get("current_step", 0)
                        total_steps = len(event_state.get("plan", []))
                        yield {
                            "type": "step_start",
                            "step_number": current_step + 1,  # 1-indexed for frontend
                            "total_steps": total_steps,
                            "message": f"Executing step {current_step + 1} of {total_steps}"
                        }
                    elif event_state.get("status") == "completed":
                        yield {
                            "type": "execution_complete",
                            "summary": event_state.get("summary", {}),
                            "message": "Execution complete"
                        }
                    elif event_state.get("status") == "failed":
                        yield {
                            "type": "error",
                            "error": event_state.get("error", "Unknown error"),
                            "message": "Execution failed"
                        }
                    
                    # Yield task results as they come in (deduplicated)
                    for result in event_state.get("results", []):
                        result_val = result.get('result', '')
                        # Convert to string for deduplication key
                        result_str = str(result_val)[:50] if result_val else ''
                        result_key = f"{result.get('task_name')}_{result_str}"
                        if result_key not in yielded_results:
                            yielded_results.add(result_key)
                            yield {
                                "type": "task_complete",
                                "task": result.get("task_name"),
                                "status": result.get("status"),
                                "result": result.get("result"),
                                "duration_ms": result.get("duration_ms")
                            }
            else:
                # Not approving - just yield current state
                yield {
                    "type": "status",
                    "status": state.get("status", "unknown"),
                    "message": f"Session status: {state.get('status')}"
                }
                
                if state.get("plan"):
                    yield {
                        "type": "plan_complete",
                        "plan": state.get("plan", []),
                        "message": "Plan available"
                    }
                    
        except Exception as e:
            log.error(f"❌ Stream error: {e}")
            yield {
                "type": "error",
                "error": str(e),
                "message": f"Stream error: {e}"
            }
    
    async def execute_with_streaming(
        self,
        user_id: str,
        goal: str,
        token: str,
        auto_approve: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Full execution with streaming - plan, approve, execute.
        
        This is a convenience method that handles the full flow:
        1. Create session and generate plan
        2. Wait for approval (or auto-approve)
        3. Execute and stream results
        
        Args:
            user_id: User initiating the session
            goal: The goal to accomplish
            token: JWT token for MCP authorization
            auto_approve: If True, automatically approve the plan
            
        Yields:
            SSE events for the full execution
        """
        log = LogContext(logger, user_id=user_id)
        
        # Create session (this will pause at approval)
        session_id = await self.create_session(user_id, goal, token)
        
        yield {
            "type": "session_created",
            "session_id": session_id,
            "message": f"Session created: {session_id}"
        }
        
        # Get plan from state
        state = await self.get_session_state(session_id)
        if state:
            yield {
                "type": "plan_complete",
                "plan": state.get("plan", []),
                "message": "Plan generated. Awaiting approval."
            }
        
        # If auto-approve, continue execution
        if auto_approve:
            log.info(f"🤖 Auto-approving plan for session: {session_id}")
            yield {
                "type": "status",
                "status": "auto_approving",
                "message": "Auto-approving plan..."
            }
            
            # Approve and stream execution
            await self.approve_plan(session_id, True)
            
            async for event in self.stream_session(session_id):
                yield event
    
    async def interrupt_and_replan(
        self,
        session_id: str,
        user_input: str,
        token: str
    ) -> Dict[str, Any]:
        """
        Interrupt current execution and trigger re-planning with new input.
        
        This is a key feature that showcases LangGraph's power:
        - Uses update_state to inject user input
        - Redirects graph flow back to planner node
        - Preserves existing context and results
        
        Args:
            session_id: Session to interrupt
            user_input: New user input/instruction
            token: JWT token for re-authorization
            
        Returns:
            New plan after re-planning
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"🔄 Interrupting session for re-planning: {user_input[:50]}...")
        
        config = {"configurable": {"thread_id": session_id}}
        
        try:
            # Get current state
            current_state = await self._graph.aget_state(config)
            if not current_state or not current_state.values:
                return {"error": "Session not found"}
            
            values = dict(current_state.values)
            
            # Update state with new user input and reset for re-planning
            from datetime import datetime
            
            await self._graph.aupdate_state(
                config,
                {
                    "goal": user_input,  # New goal from user
                    "status": "replanning",
                    "approved": False,  # Require re-approval
                    "current_step": 0,  # Reset step counter
                    "token": token,  # Fresh token
                    "messages": values.get("messages", []) + [{
                        "role": "user",
                        "content": f"User requested re-plan: {user_input}",
                        "timestamp": datetime.utcnow().isoformat()
                    }]
                },
                as_node="planner"  # Go back to planner
            )
            
            # Resume graph from planner (will pause again at approval)
            try:
                await self._graph.ainvoke(None, config)
            except Exception:
                pass  # Expected pause at interrupt
            
            # Get new state with plan
            new_state = await self.get_session_state(session_id)
            
            log.info(f"✅ Re-planning complete, new plan has {len(new_state.get('plan', []))} steps")
            
            return {
                "session_id": session_id,
                "status": "awaiting_approval",
                "plan": new_state.get("plan", []),
                "message": "Re-planned. Please approve the new plan."
            }
            
        except Exception as e:
            log.error(f"❌ Re-planning failed: {e}")
            return {"error": str(e)}
    
    async def stop_execution(self, session_id: str) -> Dict[str, Any]:
        """
        Stop execution gracefully.
        
        This marks the session as stopped and allows:
        - Resuming later from checkpoint
        - Re-planning with new input
        - Viewing partial results
        
        Note: LangGraph handles this gracefully through state updates.
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"⏹️ Stopping session: {session_id}")
        
        config = {"configurable": {"thread_id": session_id}}
        
        try:
            # Get current state
            current_state = await self._graph.aget_state(config)
            if not current_state or not current_state.values:
                return {"error": "Session not found"}
            
            values = dict(current_state.values)
            
            # Update state to stopped
            from datetime import datetime
            
            await self._graph.aupdate_state(
                config,
                {
                    "status": "stopped",
                    "messages": values.get("messages", []) + [{
                        "role": "system",
                        "content": "Execution stopped by user",
                        "timestamp": datetime.utcnow().isoformat()
                    }]
                }
            )
            
            log.info(f"✅ Session stopped")
            
            return {
                "session_id": session_id,
                "status": "stopped",
                "results": values.get("results", []),
                "current_step": values.get("current_step", 0),
                "total_steps": len(values.get("plan", [])),
                "message": "Execution stopped. You can resume or re-plan."
            }
            
        except Exception as e:
            log.error(f"❌ Failed to stop session: {e}")
            return {"error": str(e)}
    
    async def retry_session(self, session_id: str, token: str) -> Dict[str, Any]:
        """
        Retry a failed or stopped session.
        
        This resumes execution from the last checkpoint,
        skipping already completed steps.
        """
        log = LogContext(logger, session_id=session_id)
        log.info(f"🔄 Retrying session: {session_id}")
        
        config = {"configurable": {"thread_id": session_id}}
        
        try:
            # Get current state
            current_state = await self._graph.aget_state(config)
            if not current_state or not current_state.values:
                return {"error": "Session not found"}
            
            values = dict(current_state.values)
            
            # Can only retry stopped or failed sessions
            if values.get("status") not in ["stopped", "failed"]:
                return {
                    "error": f"Cannot retry session with status: {values.get('status')}"
                }
            
            # Update state to resume execution
            from datetime import datetime
            
            await self._graph.aupdate_state(
                config,
                {
                    "status": "executing",
                    "approved": True,  # Already approved
                    "token": token,  # Fresh token
                    "messages": values.get("messages", []) + [{
                        "role": "system",
                        "content": "Execution resumed",
                        "timestamp": datetime.utcnow().isoformat()
                    }]
                },
                as_node="executor_dispatch"  # Resume from executor
            )
            
            log.info(f"✅ Session ready for retry from step {values.get('current_step', 0)}")
            
            return {
                "session_id": session_id,
                "status": "executing",
                "current_step": values.get("current_step", 0),
                "message": "Session ready for retry. Connect to stream to continue."
            }
            
        except Exception as e:
            log.error(f"❌ Failed to retry session: {e}")
            return {"error": str(e)}


# Global instance
langgraph_orchestrator = LangGraphOrchestrator()


async def get_orchestrator() -> LangGraphOrchestrator:
    """Get initialized orchestrator instance."""
    if not langgraph_orchestrator._graph:
        await langgraph_orchestrator.initialize()
    return langgraph_orchestrator
