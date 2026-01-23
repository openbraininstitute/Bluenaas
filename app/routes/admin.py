from fastapi import APIRouter

from app.infrastructure.kc.auth import AdminAuthDep
from app.infrastructure.storage import (
    clear_circuit_cache,
    clear_ion_channel_cache,
    clear_mesh_cache,
    clear_single_neuron_cache,
)

router = APIRouter(prefix="/admin")


@router.delete("/cache/circuit", tags=["admin"])
async def clear_circuit_storage(_: AdminAuthDep):
    clear_circuit_cache()
    return {"message": "Circuit cache cleared successfully"}


@router.delete("/cache/single-neuron", tags=["admin"])
async def clear_single_neuron_storage(_: AdminAuthDep):
    clear_single_neuron_cache()
    return {"message": "Single neuron cache cleared successfully"}


@router.delete("/cache/mesh", tags=["admin"])
async def clear_mesh_storage(_: AdminAuthDep):
    clear_mesh_cache()
    return {"message": "Mesh cache cleared successfully"}


@router.delete("/cache/ion-channel", tags=["admin"])
async def clear_ion_channel_storage(_: AdminAuthDep):
    clear_ion_channel_cache()
    return {"message": "Ion channel cache cleared successfully"}
