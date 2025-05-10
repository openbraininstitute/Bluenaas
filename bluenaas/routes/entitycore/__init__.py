from fastapi import APIRouter
from bluenaas.config.settings import settings
from bluenaas.routes.entitycore.morphology import router as morphology_router
from bluenaas.routes.entitycore.graph import router as graph_router


entitycore_router = APIRouter(prefix=settings.BASE_PATH + "/entitycore")
entitycore_router.include_router(
    morphology_router,
)
entitycore_router.include_router(
    graph_router,
)
