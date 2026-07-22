from typing import Annotated, cast

from fastapi import Depends, Request

from app.mana_operation_ai.application.admin_service import OperationAdminService


def get_operation_admin_service(request: Request) -> OperationAdminService:
    return cast(OperationAdminService, request.app.state.operation_admin_service)


OperationAdminServiceDep = Annotated[
    OperationAdminService,
    Depends(get_operation_admin_service),
]
