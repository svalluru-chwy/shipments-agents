"""
Unified logging for Shipments Agency Platform.

Provides structured logging with consistent formatting across all packages.
"""

import logging
import sys
from typing import Optional

_logging_configured = False


def setup_logging(level: str = "INFO") -> None:
    """
    Configure root logging for the platform.

    Call once at startup (gateway main, CLI entry point, etc.).

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    global _logging_configured
    if _logging_configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    _logging_configured = True


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually ``__name__``).
        level: Optional override for the logger level.

    Returns:
        A configured :class:`logging.Logger`.
    """
    logger = logging.getLogger(name)

    if level is not None:
        logger.setLevel(level)

    return logger
