"""
Logging infrastructure for ProcureWatch.

Provides:
- Structured JSON logging for file output
- Rich console output for terminal
- Contextual logging with run/portal context
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import orjson
    
    def json_dumps(obj: Any) -> str:
        return orjson.dumps(obj, default=str).decode("utf-8")
except ImportError:
    import json
    
    def json_dumps(obj: Any) -> str:
        return json.dumps(obj, default=str)

if TYPE_CHECKING:
    from rich.console import Console


# =============================================================================
# JSON Formatter for File Logging
# =============================================================================


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key in ["portal", "run_id", "url", "page", "confidence"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        
        return json_dumps(log_data)


# =============================================================================
# Rich Console Handler
# =============================================================================


class RichConsoleHandler(logging.Handler):
    """Handler that outputs to Rich console with formatting."""
    
    def __init__(self, console: "Console | None" = None, level: int = logging.INFO):
        super().__init__(level)
        if console is None:
            from rich.console import Console
            # Force UTF-8 encoding for Windows compatibility
            console = Console(stderr=True, force_terminal=True)
        self.console = console
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            
            # Sanitize message for Windows encoding issues
            try:
                message.encode('cp1252')
            except (UnicodeEncodeError, UnicodeDecodeError):
                message = message.encode('ascii', errors='replace').decode('ascii')
            
            # Color based on level
            style = {
                logging.DEBUG: "dim",
                logging.INFO: "default",
                logging.WARNING: "yellow",
                logging.ERROR: "red",
                logging.CRITICAL: "bold red",
            }.get(record.levelno, "default")
            
            # Add contextual prefix
            prefix = ""
            if hasattr(record, "portal"):
                prefix = f"[cyan][{record.portal}][/cyan] "
            
            self.console.print(f"{prefix}[{style}]{message}[/{style}]")
            
            # Print exception if present
            if record.exc_info:
                self.console.print_exception()
                
        except Exception:
            self.handleError(record)


# =============================================================================
# Logger Configuration
# =============================================================================


def setup_logging(
    level: str = "INFO",
    log_file: Path | str | None = None,
    json_format: bool = True,
    rich_console: bool = True,
) -> logging.Logger:
    """Set up logging for ProcureWatch.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file (optional)
        json_format: Use JSON format for file logs
        rich_console: Use Rich for console output
        
    Returns:
        Root logger for procurewatch
    """
    # Force UTF-8 encoding on Windows to avoid charmap errors
    if sys.platform == "win32":
        import os
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        # Reconfigure stdout/stderr if possible (Python 3.7+)
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, OSError):
                pass
    
    # Get root logger for our package
    logger = logging.getLogger("procurewatch")
    logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    if rich_console:
        console_handler = RichConsoleHandler()
        console_handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    console_handler.setLevel(getattr(logging, level.upper()))
    logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Capture all levels to file
        
        if json_format:
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance.
    
    Args:
        name: Logger name (will be prefixed with 'procurewatch.')
        
    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"procurewatch.{name}")
    return logging.getLogger("procurewatch")


# =============================================================================
# Contextual Logging Adapter
# =============================================================================


class ContextualLogger(logging.LoggerAdapter):
    """Logger adapter that adds contextual information to log records."""
    
    def __init__(
        self,
        logger: logging.Logger,
        portal: str | None = None,
        run_id: int | None = None,
    ):
        super().__init__(logger, {})
        self.portal = portal
        self.run_id = run_id
    
    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = kwargs.get("extra", {})
        
        if self.portal:
            extra["portal"] = self.portal
        if self.run_id:
            extra["run_id"] = self.run_id
        
        kwargs["extra"] = extra
        return msg, kwargs
    
    def with_context(
        self,
        portal: str | None = None,
        run_id: int | None = None,
    ) -> "ContextualLogger":
        """Create a new logger with additional context."""
        return ContextualLogger(
            self.logger,
            portal=portal or self.portal,
            run_id=run_id or self.run_id,
        )


def get_contextual_logger(
    name: str | None = None,
    portal: str | None = None,
    run_id: int | None = None,
) -> ContextualLogger:
    """Get a contextual logger with portal/run context.
    
    Args:
        name: Logger name
        portal: Portal name for context
        run_id: Run ID for context
        
    Returns:
        ContextualLogger instance
    """
    base_logger = get_logger(name)
    return ContextualLogger(base_logger, portal=portal, run_id=run_id)
