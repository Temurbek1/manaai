from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def sanitized_request_validation_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    del request
    if not isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=500, content={"detail": "Request validation failed"})
    errors = [
        {
            "type": error.get("type", "value_error"),
            "loc": error.get("loc", ()),
            "msg": error.get("msg", "Invalid request"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})
