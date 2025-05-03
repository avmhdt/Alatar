import json
import logging
import os
import re  # Import regex module
import sys
from datetime import datetime

# Simple regex to find potential email addresses
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Regex for common API key patterns (add more as needed)
API_KEY_REGEX = re.compile(
    r"\b(sk|pk|rk|shpat|shpca|shppa)_([a-zA-Z0-9]{20,})\b"  # Common prefixes + length
)
MASK_STRING = "[REDACTED]"

# Field names in `extra["props"]` to always mask the value of
SENSITIVE_FIELD_NAMES = {
    "password",
    "token",
    "api_key",
    "secret",
    "access_token",
    "refresh_token",
    "client_secret",
    "credentials",
    "password_hash",
}


class PIIMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Mask PII in the log message itself
        original_message = record.getMessage()
        masked_msg = EMAIL_REGEX.sub(MASK_STRING, original_message)
        masked_msg = API_KEY_REGEX.sub(
            lambda m: m.group(1) + "_" + MASK_STRING, masked_msg
        )
        record.masked_message = masked_msg  # Store potentially masked message

        # Also mask PII within extra props if they exist
        if hasattr(record, "props") and isinstance(record.props, dict):
            for key, value in record.props.items():
                if isinstance(value, str):
                    # Mask based on sensitive field name
                    if key.lower() in SENSITIVE_FIELD_NAMES:
                        record.props[key] = MASK_STRING
                    else:
                        # Mask based on content regexes
                        masked_value = EMAIL_REGEX.sub(MASK_STRING, value)
                        masked_value = API_KEY_REGEX.sub(
                            lambda m: m.group(1) + "_" + MASK_STRING, masked_value
                        )
                        record.props[key] = masked_value
                # TODO: Consider masking sensitive fields even if not string (e.g., dicts)

        # If we modify record.msg or record.args, Formatter needs to be aware
        # It's often safer to add a new attribute like `masked_message`
        # and use that in the Formatter.
        return True  # Always process the record


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            # Use the masked message if available, otherwise the original
            "message": getattr(record, "masked_message", record.getMessage()),
            "logger_name": record.name,
            "func_name": record.funcName,
            "line_no": record.lineno,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Use the (potentially masked) props
        if hasattr(record, "props") and isinstance(record.props, dict):
            log_entry.update(record.props)
        return json.dumps(log_entry)


def setup_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove default handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create JSON formatter
    formatter = JsonFormatter()
    pii_filter = PIIMaskingFilter()  # Create the filter

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(pii_filter)  # Add the filter to the handler
    root_logger.addHandler(console_handler)

    # Suppress verbose logging from libraries
    logging.getLogger("uvicorn.error").propagate = False  # Handled by root logger
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)

    # Example of adding props to a log record:
    # logger = logging.getLogger(__name__)
    # logger.info("User logged in", extra={"props": {"user_id": 123}})


if __name__ == "__main__":
    # For testing the logging setup
    setup_logging()
    logger = logging.getLogger("test_logger")
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    try:
        raise ValueError("Something went wrong")
    except ValueError:
        logger.exception("An exception occurred")
    logger.info(
        "Log with extra props", extra={"props": {"request_id": "abc", "user_id": 456}}
    )
    logger.info("User test@example.com logged in.")
    logger.warning("Failed login attempt for attacker@malicious.net")
    logger.info(
        "Processing request",
        extra={"props": {"user_email": "customer@domain.tld", "request_id": "xyz"}},
    )
