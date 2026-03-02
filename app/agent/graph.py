"""LangGraph StateGraph for multi-agent orchestration.

This module builds the complete LangGraph state machine with:
- Planner node: AI-powered plan generation
- Approval node: Human-in-the-loop with interrupt()
- Executor: Parallel task execution with Send()
- Summary: Final result aggregation

Checkpointing uses AsyncMongoDBSaver for persistence.
"""

import uuid
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
from motor.motor_asyncio import AsyncIOMotorClient

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


class LangGraphOrchestrator:
    """
    LangGraph-based multi-agent orchestrator.
    
    Features:
    - Human-in-the-loop approval via interrupt()
    - Parallel task execution via Send()
    - MongoDB checkpointing for persistence
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
    
    async def initialize(self) -> None:
        """Initialize the LangGraph with checkpointer."""
        log = LogContext(logger)
        log.info("🚀 Initializing LangGraph orchestrator")
        
        # Setup MongoDB checkpointer
        self._mongo_client = AsyncIOMotorClient(self.settings.MONGODB_URL)
        self._checkpointer = AsyncMongoDBSaver(
            self._mongo_client,
            db_name=self.settings.MONGODB_DB_NAME
        )
        
        # Build the graph
        self._graph = self._build_graph()
        
        log.info("✅ LangGraph orchestrator initialized")
    
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
    
    async def create_session(
        self,
        user_id: str,
        goal: str,
        token: str
    ) -> str:
        """
        Create a new agent session and start planning.
        
        Args:
            user_id: User initiating the session
            goal: The goal to accomplish
            token: JWT token for MCP authorization
            
        Returns:
            session_id (thread_id) for the session
        """
        log = LogContext(logger, user_id=user_id)
        
        session_id = str(uuid.uuid4())
        log.info(f"📦 Creating new session: {session_id}")
        
        # Create initial state
        initial_state = create_initial_state(
            session_id=session_id,
            user_id=user_id,
            goal=goal,
            token=token
        )
        
        # Config with thread_id for checkpointing
        config = {"configurable": {"thread_id": session_id}}
        
        # Start graph execution (will pause at approval)
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
                return dict(state.values)
        except Exception as e:
            logger.error(f"Failed to get session state: {e}")
        
        return None
    
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
        session_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream session events via SSE.
        
        Yields events as the graph executes:
        - planning: Plan generation events
        - approval: Waiting for approval
        - task_start: Task beginning
        - task_complete: Task finished
        - step_complete: Step finished
        - execution_complete: All done
        """
        log = LogContext(logger, session_id=session_id)
        config = {"configurable": {"thread_id": session_id}}
        
        log.info(f"📡 Starting SSE stream for session: {session_id}")
        
        try:
            async for event in self._graph.astream(
                None,  # Resume from checkpoint
                config,
                stream_mode="values"
            ):
                # Convert LangGraph event to our SSE format
                state = event
                
                if state.get("status") == "awaiting_approval":
                    yield {
                        "type": "plan_complete",
                        "plan": state.get("plan", []),
                        "message": "Plan generated. Awaiting approval."
                    }
                elif state.get("status") == "executing":
                    yield {
                        "type": "status",
                        "status": "executing",
                        "message": "Executing plan..."
                    }
                elif state.get("status") == "completed":
                    yield {
                        "type": "execution_complete",
                        "summary": state.get("summary", {}),
                        "message": "Execution complete"
                    }
                elif state.get("status") == "failed":
                    yield {
                        "type": "error",
                        "error": state.get("error", "Unknown error"),
                        "message": "Execution failed"
                    }
                
                # Yield task results as they come in
                for result in state.get("results", []):
                    yield {
                        "type": "task_complete",
                        "task": result.get("task_name"),
                        "status": result.get("status"),
                        "result": result.get("result"),
                        "duration_ms": result.get("duration_ms")
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


# Global instance
langgraph_orchestrator = LangGraphOrchestrator()


async def get_orchestrator() -> LangGraphOrchestrator:
    """Get initialized orchestrator instance."""
    if not langgraph_orchestrator._graph:
        await langgraph_orchestrator.initialize()
    return langgraph_orchestrator
