from pathlib import Path

from app.config.settings import settings


def get_circuit_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "models" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_config_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "circuit" / "configs" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_cell_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "single-cell" / "models" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_output_location(uuid: str) -> Path:
    path = settings.STORAGE_PATH / "output" / uuid_subpath(uuid)
    return ensure_dir(path)


def uuid_subpath(uuid: str) -> Path:
    return Path(f"{uuid[0]}/{uuid[1]}/{uuid[2:]}")


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    return path
