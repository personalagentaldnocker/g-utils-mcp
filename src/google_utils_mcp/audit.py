import json
import logging
import time
import uuid

logger = logging.getLogger("google_utils_mcp.audit")


def event(
    *,
    principal: str,
    context: str,
    account: str,
    method: str,
    generation: int,
    started: float,
    decision: str,
    error: str = "",
):
    """Allowlisted fields only. Never attach exception, arguments, or response bodies."""
    logger.warning(
        json.dumps(
            {
                "request_id": uuid.uuid4().hex,
                "timestamp": time.time(),
                "principal": principal,
                "context": context,
                "account": account,
                "method": method,
                "policy_generation": generation,
                "decision": decision,
                "error_class": error,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
