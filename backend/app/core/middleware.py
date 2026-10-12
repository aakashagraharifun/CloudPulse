"""Request id propagation and structured access logging."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.errors import error_body
from app.core.request_context import request_id_var

logger = logging.getLogger("cloudpulse.access")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
REQUEST_ID_HEADER = "X-Request-ID"


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Unhandled errors: log the traceback, return the standard envelope with
                # the request id so a user can quote it, never internal details.
                logging.getLogger("cloudpulse.errors").exception(
                    "Unhandled error on %s %s", request.method, request.url.path
                )
                response = JSONResponse(
                    status_code=500,
                    content=error_body(
                        "internal_error",
                        "An unexpected error occurred.",
                        {"request_id": request_id},
                    ),
                )
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                status_code,
                extra={
                    "context": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "duration_ms": duration_ms,
                        "user_id": getattr(request.state, "user_id", None),
                    }
                },
            )
            request_id_var.reset(token)
