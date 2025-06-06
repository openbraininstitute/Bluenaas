from fastapi import APIRouter

from app.config.settings import settings
from app.routes.entitycore.generate_synapses import router as synapses_router
from app.routes.entitycore.graph import router as graph_router
from app.routes.entitycore.morphology import router as morphology_router
from app.routes.entitycore.simulation import router as simulation_router

entitycore_router = APIRouter(prefix=settings.BASE_PATH + "/entitycore")
entitycore_router.include_router(
    morphology_router,
)
entitycore_router.include_router(
    graph_router,
)
entitycore_router.include_router(simulation_router)
entitycore_router.include_router(synapses_router)
