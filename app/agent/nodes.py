"""LangGraph node implementations for multi-agent orchestration.

This module contains all the node functions for the LangGraph state machine:
- Planner: Generates execution plans using AI
- Approval: Human-in-the-loop approval checkpoint
- Executor: Executes plan steps (parallel or sequential)
- Summary: Generates final execution summary
"""

import json
import time
import asyncio
from typing import Dict, Any, List, Literal
from datetime import datetime, timezone

from langgraph.types import interrupt, Send

from app.agent.state import AgentState, PlanStep, TaskResult
from app.mcp.client import call_mcp_tool
from app.config.logging_config import get_logger, LogContext

logger = get_logger("langgraph_nodes")


# ============================================================================
# PLANNER NODE
# ============================================================================

async def planner_node(state: AgentState) -> Dict[str, Any]:
    """
    Generate an execution plan using AI.
    
    This node:
    1. Takes the user's goal
    2. Calls AI to generate a structured plan
    3. Returns the plan for approval
    
    Note: Does NOT check user permissions - that happens at execution time.
    """
    log = LogContext(logger, session_id=state["session_id"], agent_type="planner")
    log.info(f"🎯 Starting plan generation for goal: {state['goal']}")
    
    start_time = time.time()
    
    try:
        # Import here to avoid circular imports
        from app.agent.ai_service import ai_service
        
        # Generate plan using AI
        plan_steps: List[PlanStep] = []
        
        async for event in ai_service.generate_plan(
            goal=state["goal"],
            session_id=state["session_id"],
            context={"user_id": state["user_id"], "messages": state.get("messages", [])[-5:]},
            user_permissions=[]  # Don't pass permissions - AI plans freely
        ):
            if event["type"] == "plan_step":
                step = event["step"]
                # Add step_id if not present
                if "step_id" not in step:
                    step["step_id"] = f"step-{len(plan_steps)}"
                step["status"] = "pending"
                plan_steps.append(step)
                log.info(f"📍 Plan step {len(plan_steps)}: {step.get('description', 'Unknown')}")
        
        duration_ms = int((time.time() - start_time) * 1000)
        log.info(f"✅ Plan generation complete: {len(plan_steps)} steps in {duration_ms}ms")
        
        return {
            "plan": plan_steps,
            "status": "awaiting_approval",
            "messages": [{
                "role": "assistant",
                "content": f"Plan generated with {len(plan_steps)} steps. Awaiting approval.",
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        
    except Exception as e:
        log.error(f"❌ Plan generation failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "messages": [{
                "role": "system",
                "content": f"Plan generation failed: {e}",
                "timestamp": datetime.utcnow().isoformat()
            }]
        }


# ============================================================================
# APPROVAL NODE (Human-in-the-Loop)
# ============================================================================

def approval_node(state: AgentState) -> Dict[str, Any]:
    """
    Human-in-the-loop approval checkpoint.
    
    This node uses LangGraph's interrupt() to pause execution
    and wait for human approval of the plan.
    """
    log = LogContext(logger, session_id=state["session_id"], agent_type="approval")
    log.info(f"⏸️ Awaiting human approval for plan with {len(state.get('plan', []))} steps")
    
    # Use LangGraph interrupt to pause and wait for approval
    approval_response = interrupt({
        "type": "plan_approval",
        "plan": state.get("plan", []),
        "message": "Please review and approve the execution plan",
        "session_id": state["session_id"]
    })
    
    approved = approval_response.get("approved", False)
    
    log.info(f"{'✅' if approved else '❌'} Plan {'approved' if approved else 'rejected'}")
    
    return {
        "approved": approved,
        "status": "executing" if approved else "failed",
        "messages": [{
            "role": "system",
            "content": f"Plan {'approved' if approved else 'rejected'} by user",
            "timestamp": datetime.utcnow().isoformat()
        }]
    }


# ============================================================================
# EXECUTOR NODE (Fan-out for parallel execution)
# ============================================================================

async def executor_dispatch(state: AgentState) -> Dict[str, Any]:
    """
    Dispatch tasks for execution.
    
    For parallel execution, this node prepares tasks and the graph
    handles them via Send() in conditional edges.
    """
    log = LogContext(logger, session_id=state["session_id"], agent_type="executor")
    
    # Check if approved
    if not state.get("approved", False):
        log.info("❌ Plan not approved, skipping execution")
        return {"status": "failed", "error": "Plan not approved"}
    
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    
    if current_step >= len(plan):
        log.info("✅ All steps completed")
        return {}
    
    step = plan[current_step]
    sub_tasks = step.get("sub_tasks", [])
    execution_mode = step.get("execution_mode", "sequential")
    
    log.info(f"📋 Dispatching step {current_step + 1}/{len(plan)}: {step.get('description')}")
    log.info(f"   Mode: {execution_mode}, Tasks: {len(sub_tasks)}")
    
    # Update step status
    step["status"] = "running"
    
    return {
        "plan": plan,
        "messages": [{
            "role": "system",
            "content": f"Starting step {current_step + 1}: {step.get('description')}",
            "timestamp": datetime.utcnow().isoformat()
        }]
    }


def create_task_sends(state: AgentState) -> List[Send]:
    """
    Create Send() objects for parallel task execution.
    
    This is used as a conditional edge function that returns
    Send() objects to spawn parallel task executors.
    
    Includes previous step results so tasks have context from earlier steps.
    """
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    
    if current_step >= len(plan):
        return []
    
    step = plan[current_step]
    sub_tasks = step.get("sub_tasks", [])
    
    if not sub_tasks:
        return []
    
    # Collect previous results for context passing between steps
    previous_results = [
        {
            "task_name": r.get("task_name", ""),
            "status": r.get("status", ""),
            "result": r.get("result"),
            "tool": r.get("tool", "")
        }
        for r in state.get("results", [])
    ]
    
    # Create Send() for each task
    return [
        Send("task_executor", {
            "session_id": state["session_id"],
            "token": state["token"],
            "step_index": current_step,
            "task_index": i,
            "task": task,
            "goal": state["goal"],
            "step_description": step.get("description", ""),
            "previous_results": previous_results
        })
        for i, task in enumerate(sub_tasks)
    ]


async def task_executor_node(task_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single task.
    
    This node is called in parallel for each task in a step.
    It handles MCP tool calls and authorization failures.
    """
    session_id = task_state["session_id"]
    token = task_state["token"]
    task = task_state["task"]
    task_index = task_state["task_index"]
    
    log = LogContext(logger, session_id=session_id, agent_type="task_executor")
    
    task_name = task.get("name", f"Task {task_index}")
    tool_name = task.get("tool")
    tool_params = task.get("tool_params", {})
    
    log.info(f"🔄 Executing task: {task_name}")
    
    start_time = time.time()
    
    try:
        if tool_name:
            # Call MCP tool
            log.info(f"[AIFLOW] MCP Tool Called: {tool_name} with params: {json.dumps(tool_params)}")
            
            try:
                tool_result = await call_mcp_tool(tool_name, tool_params, token)
                result = {
                    "status": "success",
                    "result": tool_result,
                    "tool": tool_name
                }
            except PermissionError as pe:
                result = {
                    "status": "authorization_failed",
                    "result": str(pe),
                    "tool": tool_name
                }
            except Exception as tool_error:
                result = {
                    "status": "failed",
                    "result": str(tool_error),
                    "tool": tool_name
                }
            
            log.info(f"[AIFLOW] MCP Tool Result: {tool_name} -> {result}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "results": [TaskResult(
                    task_name=task_name,
                    tool=tool_name,
                    status=result.get("status", "success"),
                    result=result.get("result"),
                    duration_ms=duration_ms
                )]
            }
        else:
            # No tool specified - use AI to process
            from app.agent.ai_service import ai_service
            
            result = await ai_service.execute_task(
                task_name=task_name,
                task_description=task.get("description", task_name),
                context={
                    "goal": task_state["goal"],
                    "step": task_state["step_description"],
                    "tool": None,
                    "tool_params": {},
                    "previous_results": task_state.get("previous_results", [])
                },
                session_id=session_id,
                step_info={"description": task_state["step_description"]},
                token=token
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "results": [TaskResult(
                    task_name=task_name,
                    tool=None,
                    status=result.get("status", "success"),
                    result=result.get("result"),
                    duration_ms=duration_ms
                )]
            }
            
    except Exception as e:
        log.error(f"❌ Task failed: {task_name} - {e}")
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "results": [TaskResult(
                task_name=task_name,
                tool=tool_name,
                status="failed",
                result=None,
                error=str(e),
                duration_ms=duration_ms
            )]
        }


def step_aggregator_node(state: AgentState) -> Dict[str, Any]:
    """
    Aggregate results from parallel task execution and advance to next step.
    
    This node:
    1. Checks if any task failed with authorization error
    2. Updates current_step to advance to next step
    3. Marks step as completed
    """
    log = LogContext(logger, session_id=state["session_id"], agent_type="aggregator")
    
    results = state.get("results", [])
    current_step = state.get("current_step", 0)
    plan = state.get("plan", [])
    
    # Check for authorization failures
    auth_failures = [r for r in results if r.get("status") == "authorization_failed"]
    if auth_failures:
        failed_task = auth_failures[0]
        log.error(f"🚫 Authorization failure in task: {failed_task.get('task_name')}")
        return {
            "status": "failed",
            "error": f"Authorization failed: {failed_task.get('result')}",
            "messages": [{
                "role": "system",
                "content": f"Execution stopped due to authorization failure",
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
    
    # Update step status
    if current_step < len(plan):
        plan[current_step]["status"] = "completed"
    
    # Advance to next step
    next_step = current_step + 1
    
    log.info(f"✅ Step {current_step + 1} completed, advancing to step {next_step + 1}")
    
    return {
        "current_step": next_step,
        "plan": plan,
        "messages": [{
            "role": "system",
            "content": f"Completed step {current_step + 1}/{len(plan)}",
            "timestamp": datetime.utcnow().isoformat()
        }]
    }


# ============================================================================
# SUMMARY NODE
# ============================================================================

async def summary_node(state: AgentState) -> Dict[str, Any]:
    """
    Generate final execution summary.
    
    Called after all steps are completed (or on failure).
    """
    log = LogContext(logger, session_id=state["session_id"], agent_type="summary")
    log.info(f"📊 Generating execution summary")
    
    results = state.get("results", [])
    plan = state.get("plan", [])
    
    # Calculate statistics
    total_tasks = len(results)
    successful_tasks = sum(1 for r in results if r.get("status") == "success")
    failed_tasks = sum(1 for r in results if r.get("status") in ["failed", "authorization_failed"])
    total_duration = sum(r.get("duration_ms", 0) for r in results)
    
    # Determine overall status
    if state.get("status") == "failed":
        overall_status = "failed"
    elif failed_tasks > 0:
        overall_status = "partial_success"
    else:
        overall_status = "success"
    
    summary = {
        "goal": state.get("goal"),
        "overall_status": overall_status,
        "total_steps": len(plan),
        "completed_steps": sum(1 for s in plan if s.get("status") == "completed"),
        "total_tasks": total_tasks,
        "successful_tasks": successful_tasks,
        "failed_tasks": failed_tasks,
        "total_duration_ms": total_duration,
        "error": state.get("error")
    }
    
    log.info(f"✅ Summary: {overall_status} - {successful_tasks}/{total_tasks} tasks succeeded")
    
    return {
        "summary": summary,
        "status": "completed",
        "messages": [{
            "role": "assistant",
            "content": f"Execution complete: {successful_tasks}/{total_tasks} tasks succeeded",
            "timestamp": datetime.utcnow().isoformat()
        }]
    }


# ============================================================================
# ROUTING FUNCTIONS
# ============================================================================

def should_continue(state: AgentState) -> Literal["executor", "summary"]:
    """Determine if execution should continue or finish."""
    if state.get("status") == "failed":
        return "summary"
    
    current_step = state.get("current_step", 0)
    plan = state.get("plan", [])
    
    if current_step >= len(plan):
        return "summary"
    
    return "executor"


def check_approval(state: AgentState) -> Literal["executor", "summary"]:
    """Check if plan was approved."""
    if state.get("approved", False):
        return "executor"
    return "summary"
