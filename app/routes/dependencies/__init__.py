from entitysdk.common import ProjectContext
from fastapi import Header


from typing import Annotated


ProjectContextDep = Annotated[ProjectContext, Header()]
