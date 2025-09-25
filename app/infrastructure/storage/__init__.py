import shutil
from pathlib import Path
from uuid import UUID

from app.config.settings import settings


def uuid_subpath(uuid: UUID) -> Path:
    uuid_str = str(uuid)
    return Path(f"{uuid_str[0]}/{uuid_str[1]}/{uuid_str[2:]}")


def create_file(path: Path, content: bytes) -> None:
    """Create file."""
    if not path.parent.exists():
        path.parent.mkdir(parents=True)

    with open(path, "bw") as f:
        f.write(content)


def copy_file_content(source_file: Path, target_file: Path):
    with open(source_file, "br") as src, open(target_file, "bw") as dst:
        dst.write(src.read())


def rm_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    return path


def get_circuit_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "model" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "simulation" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_output_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "output" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_neuron_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "single-neuron" / "model" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_neuron_validation_output_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "single-neuron" / "validation-output" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_mesh_location(uuid: UUID) -> Path:
    path = settings.STORAGE_PATH / "mesh" / "mesh" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_mesh_skeletonization_output_location(uuid: UUID) -> Path:
    # TODO Revert back once Ultraliser has FS IO locking fixed.
    # path = settings.STORAGE_PATH / "mesh" / "skeletonization-output" / uuid_subpath(uuid)
    path = Path("/tmp") / "mesh" / "skeletonization-output" / uuid_subpath(uuid)
    return ensure_dir(path)
