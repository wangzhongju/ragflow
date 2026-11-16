"""JSON logging. INFO never carries secrets, full prompts or user content."""

import logging

import structlog


def configure_logging() -> None:
    """Set structlog to emit one JSON object per line."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def get_logger(**bound):
    """A logger with the given context already attached."""
    return structlog.get_logger().bind(**bound)
