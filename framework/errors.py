from __future__ import annotations

from .models import ErrorCode, ErrorPayload


def make_error(code: ErrorCode, message: str, likely_cause: str, next_step: str) -> ErrorPayload:
    return ErrorPayload(
        code=code,
        message=message,
        likely_cause=likely_cause,
        next_step=next_step,
    )
