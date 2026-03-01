"""LangGraph agent with plan mode and checkpoint support."""

import uuid
from typing import Dict, Any, List, Optional, TypedDict, Annotated
from datetime import datetime, timezone
from operator import add

from app.checkpoints import mongodb_checkpoint, redis_checkpoint
from app.models import AgentState


class PlanStep(TypedDict):
    """A single step in the agent's plan."""
    step_id: str
    description: str
    action: str
    status: str  # "pending", "in_progress", "completed", "failed"
    result: Optional[Dict[str, Any]]


class AgentGraphState(TypedDict):
    """State for the LangGraph agent."""
    session_id: str
    user_id: str
    messages: Annotated[List[Dict[str, Any]], add]
    plan: List[PlanStep]
    current_step: int
    is_planning_mode: bool
    context: Dict[str, Any]
    final_result: Optional[Dict[str, Any]]


class PlanModeAgent:
    """
    LangGraph-style agent with plan mode support.
    
    Features:
    - Plan mode: Creates and executes multi-step plans
    - Hot state checkpoints: Stored in MongoDB
    - Cold state checkpoints: Stored in Redis for long-term storage
    """
    
    def __init__(self):
        self.available_actions = {
            "search": self._action_search,
            "analyze": self._action_analyze,
            "transform": self._action_transform,
            "store": self._action_store,
            "retrieve": self._action_retrieve,
        }
    
    async def create_session(self, user_id: str) -> str:
        """Create a new agent session."""
        session_id = str(uuid.uuid4())
        
        initial_state = AgentState(
            session_id=session_id,
            user_id=user_id,
            state_type="hot",
            state_data={
                "messages": [],
                "plan": [],
                "current_step": 0,
                "is_planning_mode": False,
                "context": {},
                "final_result": None
            },
            plan=[],
            current_step=0,
            is_complete=False
        )
        
        await mongodb_checkpoint.save_checkpoint(initial_state)
        return session_id
    
    async def _get_state(self, session_id: str) -> Optional[AgentState]:
        """Get current agent state from hot storage."""
        return await mongodb_checkpoint.get_checkpoint(session_id)
    
    async def _save_state(self, state: AgentState) -> str:
        """Save agent state to hot storage."""
        return await mongodb_checkpoint.save_checkpoint(state)
    
    async def _migrate_to_cold(self, session_id: str, ttl_seconds: int = 86400) -> str:
        """Migrate agent state from hot to cold storage."""
        state = await self._get_state(session_id)
        if state:
            return await redis_checkpoint.migrate_to_cold(state, ttl_seconds)
        return ""
    
    async def enter_plan_mode(self, session_id: str, goal: str) -> Dict[str, Any]:
        """Enter planning mode and generate a plan."""
        state = await self._get_state(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        
        # Generate plan based on goal
        plan = await self._generate_plan(goal)
        
        state.state_data["is_planning_mode"] = True
        state.state_data["plan"] = plan
        state.state_data["current_step"] = 0
        state.plan = plan
        state.current_step = 0
        
        await self._save_state(state)
        
        return {
            "session_id": session_id,
            "mode": "planning",
            "plan": plan,
            "total_steps": len(plan)
        }
    
    async def _generate_plan(self, goal: str) -> List[Dict[str, Any]]:
        """Generate a plan based on the goal."""
        # Simple plan generation (in production, use LLM)
        steps = []
        
        # Basic planning logic
        if "search" in goal.lower() or "find" in goal.lower():
            steps.append(self._create_step("Search for relevant information", "search"))
            steps.append(self._create_step("Analyze search results", "analyze"))
        
        if "analyze" in goal.lower() or "process" in goal.lower():
            steps.append(self._create_step("Process and analyze data", "analyze"))
            steps.append(self._create_step("Transform results", "transform"))
        
        if "store" in goal.lower() or "save" in goal.lower():
            steps.append(self._create_step("Store processed data", "store"))
        
        # Default steps if no specific actions detected
        if not steps:
            steps = [
                self._create_step("Understand the request", "analyze"),
                self._create_step("Process the information", "transform"),
                self._create_step("Generate response", "store")
            ]
        
        return steps
    
    def _create_step(self, description: str, action: str) -> Dict[str, Any]:
        """Create a plan step."""
        return {
            "step_id": str(uuid.uuid4()),
            "description": description,
            "action": action,
            "status": "pending",
            "result": None
        }
    
    async def execute_step(self, session_id: str) -> Dict[str, Any]:
        """Execute the current step in the plan."""
        state = await self._get_state(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        
        plan = state.state_data.get("plan", [])
        current_step = state.current_step
        
        if current_step >= len(plan):
            return {
                "session_id": session_id,
                "status": "completed",
                "message": "All steps completed"
            }
        
        step = plan[current_step]
        step["status"] = "in_progress"
        
        # Execute the action
        action_func = self.available_actions.get(step["action"])
        if action_func:
            result = await action_func(state.state_data.get("context", {}))
            step["result"] = result
            step["status"] = "completed"
        else:
            step["status"] = "failed"
            step["result"] = {"error": f"Unknown action: {step['action']}"}
        
        # Update state
        state.state_data["plan"] = plan
        state.state_data["current_step"] = current_step + 1
        state.current_step = current_step + 1
        state.plan = plan
        
        # Check if all steps completed
        if state.current_step >= len(plan):
            state.is_complete = True
            state.state_data["is_planning_mode"] = False
        
        await self._save_state(state)
        
        return {
            "session_id": session_id,
            "step": step,
            "current_step": state.current_step,
            "total_steps": len(plan),
            "is_complete": state.is_complete
        }
    
    async def execute_all_steps(self, session_id: str) -> Dict[str, Any]:
        """Execute all remaining steps in the plan."""
        results = []
        while True:
            result = await self.execute_step(session_id)
            results.append(result)
            if result.get("is_complete") or result.get("status") == "completed":
                break
        
        return {
            "session_id": session_id,
            "execution_results": results,
            "status": "completed"
        }
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> Dict[str, Any]:
        """Add a message to the agent's conversation."""
        state = await self._get_state(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        messages = state.state_data.get("messages", [])
        messages.append(message)
        state.state_data["messages"] = messages
        
        await self._save_state(state)
        
        return {
            "session_id": session_id,
            "message_added": message,
            "total_messages": len(messages)
        }
    
    async def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Get the current state of an agent session."""
        state = await self._get_state(session_id)
        if not state:
            # Try cold storage
            state = await redis_checkpoint.get_cold_checkpoint(session_id)
        
        if not state:
            raise ValueError(f"Session {session_id} not found")
        
        return {
            "session_id": state.session_id,
            "user_id": state.user_id,
            "state_type": state.state_type,
            "is_planning_mode": state.state_data.get("is_planning_mode", False),
            "plan": state.plan,
            "current_step": state.current_step,
            "is_complete": state.is_complete,
            "messages": state.state_data.get("messages", []),
            "created_at": state.created_at.isoformat() if state.created_at else None,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None
        }
    
    async def archive_session(self, session_id: str, ttl_days: int = 30) -> Dict[str, Any]:
        """Archive a session to cold storage and remove from hot storage."""
        ttl_seconds = ttl_days * 24 * 60 * 60
        
        # Migrate to cold storage
        cold_key = await self._migrate_to_cold(session_id, ttl_seconds)
        
        # Remove from hot storage
        await mongodb_checkpoint.delete_checkpoint(session_id)
        
        return {
            "session_id": session_id,
            "status": "archived",
            "cold_storage_key": cold_key,
            "ttl_days": ttl_days
        }
    
    # Action implementations
    async def _action_search(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Search action implementation."""
        return {
            "action": "search",
            "status": "success",
            "results": ["Result 1", "Result 2", "Result 3"]
        }
    
    async def _action_analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze action implementation."""
        return {
            "action": "analyze",
            "status": "success",
            "analysis": "Analysis complete"
        }
    
    async def _action_transform(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Transform action implementation."""
        return {
            "action": "transform",
            "status": "success",
            "transformed_data": context
        }
    
    async def _action_store(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Store action implementation."""
        return {
            "action": "store",
            "status": "success",
            "stored": True
        }
    
    async def _action_retrieve(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve action implementation."""
        return {
            "action": "retrieve",
            "status": "success",
            "data": context
        }


# Global instance
plan_mode_agent = PlanModeAgent()
