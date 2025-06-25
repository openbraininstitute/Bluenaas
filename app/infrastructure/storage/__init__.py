from pathlib import Path

from app.config.settings import settings
from app.constants import DEFAULT_CIRCUIT_ID


def uuid_subpath(uuid: str) -> Path:
    return Path(f"{uuid[0]}/{uuid[1]}/{uuid[2:]}")


def create_file(path: Path, content: bytes) -> None:
    """Create file."""
    with open(path, "bw") as f:
        f.write(content)


def copy_file_content(source_file: Path, target_file: Path):
    with open(source_file, "br") as src, open(target_file, "bw") as dst:
        dst.write(src.read())


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    return path


def get_default_circuit_location() -> Path:
    return Path("/app/circuit")


def get_circuit_location(uuid: str) -> Path:
    if uuid == DEFAULT_CIRCUIT_ID:
        return get_default_circuit_location()

    path = settings.STORAGE_PATH / "circuit" / "model" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "simulation" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_output_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "output" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_cell_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "single-cell" / "model" / uuid_subpath(uuid)
    return ensure_dir(path)
