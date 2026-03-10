from entitysdk.common import ProjectContext
from fastapi import Header


from typing import Annotated

from app.infrastructure.kc.auth import AdminAuthDep, UserAuthDep


ProjectContextDep = Annotated[ProjectContext, Header()]

__all__ = ["ProjectContextDep", "UserAuthDep", "AdminAuthDep"]
