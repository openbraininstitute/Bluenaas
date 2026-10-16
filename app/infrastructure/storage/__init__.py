import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid5, UUID, NAMESPACE_URL
from loguru import logger

from app.config.settings import settings
from app.infrastructure.storage.epoch import CacheKind, current_epoch, epoch_dir_name


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
    """Remove directory if exists, log warning if fails."""
    if path.exists():
        shutil.rmtree(
            path,
            onexc=lambda func, path, exc_info: logger.warning(
                f"Failed: {func.__name__} on {path}: {exc_info}"
            ),
        )


def rm_dir_parallel(path: Path, *, workers: int) -> None:
    """Like `rm_dir`, but removes different parts of the tree at the same time.

    Every remove is a round trip to the server on a network filesystem, so a tree with many small
    files is slow to remove one file after another.
    """
    if not path.exists():
        return

    # Split the top of the tree into enough subtrees to keep the workers busy. The directories
    # that were split are removed once everything below them is gone.
    split_dirs: list[Path] = []
    leaves: list[Path] = []
    to_split = [path]
    while to_split and len(leaves) + len(to_split) < workers * 4:
        next_to_split: list[Path] = []
        for directory in to_split:
            try:
                with os.scandir(directory) as it:
                    children = list(it)
            except OSError as ex:
                logger.warning(f"Failed: scandir on {directory}: {ex}")
                leaves.append(directory)
                continue

            subdirs = [Path(c.path) for c in children if c.is_dir(follow_symlinks=False)]
            if not subdirs:
                leaves.append(directory)
                continue

            for child in children:
                if not child.is_dir(follow_symlinks=False):
                    try:
                        os.unlink(child.path)
                    except OSError as ex:
                        logger.warning(f"Failed: unlink on {child.path}: {ex}")
            split_dirs.append(directory)
            next_to_split.extend(subdirs)
        to_split = next_to_split

    subtrees = leaves + to_split

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(rm_dir, subtrees))

    for directory in reversed(split_dirs):
        try:
            directory.rmdir()
        except OSError as ex:
            logger.warning(f"Failed: rmdir on {directory}: {ex}")


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    return path


def epoch_root(kind: CacheKind) -> Path:
    """Root of the cache of the given kind in the epoch the running job uses."""
    return settings.STORAGE_PATH / kind.value / epoch_dir_name(current_epoch(kind))


def get_circuit_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.CIRCUIT) / "model" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.CIRCUIT) / "simulation" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_circuit_simulation_output_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.CIRCUIT) / "output" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_neuron_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.SINGLE_NEURON) / "model" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_single_neuron_validation_output_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.SINGLE_NEURON) / "validation-output" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_mesh_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.MESH) / "mesh" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_ion_channel_build_location(uuid: UUID) -> Path:
    path = epoch_root(CacheKind.ION_CHANNEL) / "build" / uuid_subpath(uuid)
    return ensure_dir(path)


def get_model_candidate_location(morphology_id: UUID, emodel_id: UUID) -> Path:
    composite_id = uuid5(NAMESPACE_URL, f"{morphology_id}:{emodel_id}")
    path = epoch_root(CacheKind.SINGLE_NEURON) / "model-candidate" / uuid_subpath(composite_id)
    return ensure_dir(path)


def get_compatibility_result_location(morphology_id: UUID, emodel_id: UUID) -> Path:
    composite_id = uuid5(NAMESPACE_URL, f"{morphology_id}:{emodel_id}")
    path = epoch_root(CacheKind.SINGLE_NEURON) / "compatibility" / uuid_subpath(composite_id)
    return ensure_dir(path)


# download_memodel stages each morphology format in its own subdirectory, in this order of preference
MORPHOLOGY_FORMAT_PREFERENCE = ("asc", "swc", "h5")


def find_morphology_file(morphology_dir: Path) -> Path:
    """Locate the morphology file to load, whether staged flat or in per-format subdirectories.

    Only files with a known morphology extension (case-insensitive) are considered, and the
    preferred format wins within a directory.
    """
    for candidate_dir in (
        morphology_dir,
        *(morphology_dir / fmt for fmt in MORPHOLOGY_FORMAT_PREFERENCE),
    ):
        files = sorted(p for p in candidate_dir.glob("*") if p.is_file())
        for fmt in MORPHOLOGY_FORMAT_PREFERENCE:
            for file in files:
                if file.suffix.lower() == f".{fmt}":
                    return file

    raise FileNotFoundError(f"No morphology file found in {morphology_dir}")
