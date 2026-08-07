from typing import Annotated, cast

from fastapi import Depends, Request

from app.mana_ai.application.service import ManaAIAnalysisService


def get_mana_ai_analysis_service(request: Request) -> ManaAIAnalysisService:
    return cast(ManaAIAnalysisService, request.app.state.mana_ai_analysis_service)


ManaAIAnalysisServiceDep = Annotated[
    ManaAIAnalysisService,
    Depends(get_mana_ai_analysis_service),
]
