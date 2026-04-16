"""Content-addressable compilation cache for nrnivmodl MOD files."""

import hashlib
import shutil
import subprocess
from pathlib import Path

from filelock import FileLock
from loguru import logger

from app.config.settings import settings
from app.constants import READY_MARKER_FILE_NAME


def compute_mod_hash(mod_dir: Path) -> str:
    """Compute a deterministic SHA-256 hash of all .mod files in a directory."""
    mod_files = sorted(mod_dir.glob("*.mod"))
    if not mod_files:
        raise FileNotFoundError(f"No .mod files found in {mod_dir}")

    hasher = hashlib.sha256()
    for mod_file in mod_files:
        hasher.update(mod_file.name.encode())
        hasher.update(b"\0")
        hasher.update(mod_file.read_bytes())
    return hasher.hexdigest()


def get_compilation_cache_path(mod_hash: str) -> Path:
    """Return the cache directory path for a given hash."""
    path = settings.STORAGE_PATH / "compilation-cache" / mod_hash[:2] / mod_hash[2:4] / mod_hash[4:]
    path.mkdir(parents=True, exist_ok=True)
    return path


def compile_with_cache(model_path: Path, mod_dir_name: str) -> None:
    """Compile MOD files using a content-addressable cache.

    1. If model already has compiled output, return early.
    2. Hash MOD file contents to get a cache key.
    3. On cache hit, copy compiled artifacts to model directory.
    4. On cache miss, compile, store in cache, then copy to model directory.
    """
    compiled_path = model_path / "x86_64"
    if compiled_path.is_dir():
        logger.debug("Found already compiled mechanisms")
        return

    mod_dir = model_path / mod_dir_name
    if not mod_dir.is_dir():
        raise FileNotFoundError(f"'{mod_dir_name}' folder not found under {model_path}")

    mod_hash = compute_mod_hash(mod_dir)
    cache_path = get_compilation_cache_path(mod_hash)
    cache_ready = cache_path / READY_MARKER_FILE_NAME

    if cache_ready.exists():
        logger.debug(f"Compilation cache hit for hash {mod_hash[:12]}")
        shutil.copytree(cache_path / "x86_64", compiled_path)
        return

    lock = FileLock(cache_path / "dir.lock")

    with lock.acquire(timeout=5 * 60):
        if cache_ready.exists():
            logger.debug(f"Compilation cache hit (after lock) for hash {mod_hash[:12]}")
            shutil.copytree(cache_path / "x86_64", compiled_path)
            return

        logger.info(f"Compilation cache miss for hash {mod_hash[:12]}, compiling")

        cache_mod_dir = cache_path / mod_dir_name
        if cache_mod_dir.exists():
            shutil.rmtree(cache_mod_dir)
        shutil.copytree(mod_dir, cache_mod_dir)

        cmd = ["nrnivmodl", "-incflags", "-DDISABLE_REPORTINGLIB", mod_dir_name]
        compilation_output = subprocess.check_output(cmd, cwd=cache_path, text=True)
        logger.debug(compilation_output)

        cache_ready.touch()

    shutil.copytree(cache_path / "x86_64", compiled_path)
