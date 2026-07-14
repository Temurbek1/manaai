from typing import Annotated, cast

from fastapi import Depends, Request

from app.services.openai_service import OpenAIService


def get_openai_service(request: Request) -> OpenAIService:
    return cast(OpenAIService, request.app.state.openai_service)


OpenAIServiceDep = Annotated[OpenAIService, Depends(get_openai_service)]
