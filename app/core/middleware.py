import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"
EXPOSED_RESPONSE_HEADERS = [REQUEST_ID_HEADER, PROCESS_TIME_HEADER]


async def request_trace_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    started_at = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[PROCESS_TIME_HEADER] = f"{elapsed_ms:.3f}"
    return response


def normalize_request_id(value: str | None) -> str:
    if value is not None and 0 < len(value) <= 128 and "\r" not in value and "\n" not in value:
        return value
    return str(uuid.uuid4())
