"""
Custom DRF API Exception Handler.

Enforces the standardized 3-part error contract across all 4xx/5xx responses:
{
    "detail": "Human-readable summary message.",
    "code": "stable_snake_case_error_code",
    "fields": { "field_name": ["error message"] }  # Present only on validation errors
}

Success responses are NEVER wrapped.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

STATUS_TO_CODE: dict[int, str] = {
    400: "bad_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    429: "throttled",
    500: "internal_server_error",
}


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Optional[Response]:
    """
    Standardized DRF exception handler ensuring a consistent error response contract.
    """
    response: Optional[Response] = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data

    # 1. Validation Errors with field-specific errors
    if isinstance(exc, ValidationError) and isinstance(data, dict) and "detail" not in data:
        fields: dict[str, list[str]] = {}
        for key, value in data.items():
            if isinstance(value, list):
                fields[key] = [str(item) for item in value]
            elif isinstance(value, dict):
                # Flatten or convert nested dict error
                fields[key] = [str(value)]
            else:
                fields[key] = [str(value)]

        response.data = {
            "detail": "Validation failed.",
            "code": "validation_error",
            "fields": fields,
        }
        return response

    # 2. Structured dictionary responses
    if isinstance(data, dict):
        raw_detail = data.get("detail", "Request failed.")
        if isinstance(raw_detail, list):
            detail_str = str(raw_detail[0]) if raw_detail else "Request failed."
        else:
            detail_str = str(raw_detail)

        code_str = data.get("code") or STATUS_TO_CODE.get(response.status_code, "error")

        payload: dict[str, Any] = {
            "detail": detail_str,
            "code": str(code_str),
        }

        # Preserve field errors if passed
        if "fields" in data and isinstance(data["fields"], dict):
            payload["fields"] = data["fields"]

        response.data = payload
        return response

    # 3. Direct list responses (e.g. ['Invalid action'])
    if isinstance(data, list):
        detail_str = str(data[0]) if data else "Request failed."
        response.data = {
            "detail": detail_str,
            "code": STATUS_TO_CODE.get(response.status_code, "error"),
        }
        return response

    return response

