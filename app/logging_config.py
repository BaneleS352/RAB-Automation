"""Structured logging configuration for the RAB Automation service."""

import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configure application-wide logging.

    Args:
        log_level: The logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    normalized = log_level.upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if normalized not in valid_levels:
        # Use print to avoid recursion before logging is configured
        print(f"WARNING: Invalid LOG_LEVEL '{log_level}' — falling back to INFO (valid: {', '.join(sorted(valid_levels))})", file=sys.stderr)
        normalized = "INFO"
    numeric_level = getattr(logging, normalized, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
