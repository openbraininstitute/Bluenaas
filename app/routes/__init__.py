from fastapi import APIRouter

from app.routes.circuit import router as circuit_router
from app.routes.single_neuron import router as single_neuron_router

router = APIRouter()

router.include_router(circuit_router)
router.include_router(single_neuron_router)
