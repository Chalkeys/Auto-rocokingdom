import json
import logging
import os

from config import runtime_path

AUDIT_LOGGER_NAME = "audit"


def setup_logging() -> None:
    logs_dir = runtime_path("logs")
    os.makedirs(logs_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(logs_dir, "runtime.log"), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    audit_logger.handlers.clear()
    audit_handler = logging.FileHandler(os.path.join(logs_dir, "audit.log"), encoding="utf-8")
    audit_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    audit_logger.addHandler(audit_handler)


def log_audit(event: str, **payload: object) -> None:
    data = {"event": event, **payload}
    logging.getLogger(AUDIT_LOGGER_NAME).info(
        json.dumps(data, ensure_ascii=False, sort_keys=True)
    )
