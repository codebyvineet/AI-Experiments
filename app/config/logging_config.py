"""Structured logging configuration for the application."""

import logging
import sys
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from functools import wraps
import traceback


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for better debugging and observability."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "session_id"):
            log_data["session_id"] = record.session_id
        if hasattr(record, "agent_type"):
            log_data["agent_type"] = record.agent_type
        if hasattr(record, "phase"):
            log_data["phase"] = record.phase
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with colors."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        
        # Build prefix with context
        prefix_parts = [f"{color}{self.BOLD}[{record.levelname}]{self.RESET}"]
        prefix_parts.append(f"\033[90m{timestamp}\033[0m")
        prefix_parts.append(f"\033[94m{record.name}\033[0m")
        
        if hasattr(record, "request_id"):
            prefix_parts.append(f"\033[95mreq:{record.request_id[:8]}\033[0m")
        if hasattr(record, "session_id"):
            prefix_parts.append(f"\033[93msess:{record.session_id[:8]}\033[0m")
        if hasattr(record, "agent_type"):
            prefix_parts.append(f"\033[96magent:{record.agent_type}\033[0m")
        
        prefix = " ".join(prefix_parts)
        message = record.getMessage()
        
        # Add extra data if present
        if hasattr(record, "extra_data") and record.extra_data:
            if isinstance(record.extra_data, dict):
                data_str = json.dumps(record.extra_data, indent=2, default=str)
                message += f"\n{color}  └─ {data_str}{self.RESET}"
        
        # Add duration if present
        if hasattr(record, "duration_ms"):
            message += f" \033[90m({record.duration_ms}ms)\033[0m"
        
        return f"{prefix} │ {message}"


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configure application logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    if json_format:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    
    root_logger.addHandler(console_handler)
    
    # Set third-party loggers to WARNING
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "httpx", "httpcore"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding structured context to logs."""
    
    def __init__(
        self,
        logger: logging.Logger,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        phase: Optional[str] = None
    ):
        self.logger = logger
        self.context = {
            "request_id": request_id,
            "user_id": user_id,
            "session_id": session_id,
            "agent_type": agent_type,
            "phase": phase
        }
        # Filter out None values
        self.context = {k: v for k, v in self.context.items() if v is not None}
    
    def _log(self, level: int, msg: str, extra_data: Optional[Dict[str, Any]] = None, **kwargs):
        extra = {**self.context}
        if extra_data:
            extra["extra_data"] = extra_data
        if "duration_ms" in kwargs:
            extra["duration_ms"] = kwargs.pop("duration_ms")
        self.logger.log(level, msg, extra=extra)
    
    def debug(self, msg: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log(logging.DEBUG, msg, data, **kwargs)
    
    def info(self, msg: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log(logging.INFO, msg, data, **kwargs)
    
    def warning(self, msg: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log(logging.WARNING, msg, data, **kwargs)
    
    def error(self, msg: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log(logging.ERROR, msg, data, **kwargs)
    
    def ai_request(self, prompt: str, model: str = "gemini"):
        """Log AI request - full prompt with grepable prefix."""
        # Escape newlines for single-line grepable output
        escaped_prompt = prompt.replace('\n', '\\n')
        self.logger.info(f"[AIFLOW] AI Prompt: {escaped_prompt}")
        self.info(f"🤖 AI Request to {model}", data={"prompt_length": len(prompt)})
    
    def ai_response(self, response: str, duration_ms: int):
        """Log AI response - full response with grepable prefix."""
        # Escape newlines for single-line grepable output
        escaped_response = response.replace('\n', '\\n')
        self.logger.info(f"[AIFLOW] AI Response: {escaped_response}")
        self.info(f"✅ AI Response received", data={"response_length": len(response)}, duration_ms=duration_ms)
    
    def agent_start(self, agent_name: str, task: str):
        """Log agent starting."""
        self.info(f"🚀 Agent '{agent_name}' starting", data={"task": task})
    
    def agent_complete(self, agent_name: str, result: Any, duration_ms: int):
        """Log agent completion - full result without truncation."""
        self.info(f"✅ Agent '{agent_name}' completed", data={"result": str(result)}, duration_ms=duration_ms)
    
    def step_start(self, step_num: int, description: str, mode: str):
        """Log step starting."""
        self.info(f"📍 Step {step_num}: {description}", data={"execution_mode": mode})
    
    def step_complete(self, step_num: int, duration_ms: int):
        """Log step completion."""
        self.info(f"✓ Step {step_num} completed", duration_ms=duration_ms)


# Initialize logging on module import
setup_logging(level="DEBUG", json_format=False)
