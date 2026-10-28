"""Content-addressable compilation cache for nrnivmodl MOD files."""

import hashlib
import shutil
from pathlib import Path

from filelock import FileLock
from loguru import logger

from app.constants import MECHANISMS_DIR_NAME, READY_MARKER_FILE_NAME
from app.infrastructure.storage import epoch_root
from app.infrastructure.storage.epoch import CacheKind


def compiled_mechanisms_path(model_path: Path) -> Path:
    return model_path / MECHANISMS_DIR_NAME


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


def compute_cache_key(
    mod_dir: Path, bundled_mod_dir: Path, incflags: str, neuron_version: str
) -> str:
    """Cache key for a compilation: the model MODs plus everything else that
    can change the build — BlueCelluLab's bundled technical MODs, the compiler
    flags and the NEURON version — so upgrades invalidate cached builds.
    """
    parts = []
    if mod_dir.is_dir() and any(mod_dir.glob("*.mod")):
        parts.append(compute_mod_hash(mod_dir))
    parts.extend([compute_mod_hash(bundled_mod_dir), incflags, neuron_version])
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _bcl_cache_inputs() -> tuple[Path, str, str]:
    """BlueCelluLab inputs to the cache key (kept lazy: importing bluecellulab
    imports NEURON).
    """
    from bluecellulab.mod_compilation import (
        DEFAULT_INCFLAGS,
        internal_mods_path,
        neuron_version,
    )

    return internal_mods_path(), DEFAULT_INCFLAGS, neuron_version()


def get_compilation_cache_path(mod_hash: str) -> Path:
    """Return the cache directory path for a given hash."""
    path = epoch_root(CacheKind.COMPILATION) / mod_hash[:2] / mod_hash[2:4] / mod_hash[4:]
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bcl_compile_mods(input_dirs: list[Path], output_dir: Path) -> Path:
    """Compile MOD files with BlueCelluLab's ``compile_mods``.

    ``with_internal_mods`` adds BlueCelluLab's bundled technical MODs
    (``vecevent``/``VecStim``, ``TTXDynamicsSwitch``, ``InhPoissonStim`` and
    the current sources), so models do not have to ship them; a duplicate
    mechanism in the model is overridden by the bundled copy with a warning.
    ``load=False`` because mechanisms are registered into NEURON separately
    by ``neuron_runtime.load``.
    """
    from bluecellulab.mod_compilation import compile_mods

    return compile_mods(
        input_dirs=input_dirs,
        output_dir=output_dir,
        with_internal_mods=True,
        load=False,
    )


def compile_with_cache(model_path: Path, mod_dir_name: str) -> None:
    """Compile MOD files using a content-addressable cache.

    1. If model already has compiled output, return early.
    2. Hash model MODs, BlueCelluLab's bundled MODs, flags and the NEURON
       version to get a cache key.
    3. On cache hit, copy compiled artifacts to model directory.
    4. On cache miss, compile, store in cache, then copy to model directory.

    A model with no MOD files of its own still gets BlueCelluLab's bundled
    technical mechanisms compiled, so passive models keep the mechanisms the
    stimulus machinery needs (``InhPoissonStim``, ``vecevent``, ...).
    """
    compiled_path = compiled_mechanisms_path(model_path)
    if compiled_path.is_dir():
        logger.debug("Found already compiled mechanisms")
        return

    mod_dir = model_path / mod_dir_name
    bundled_mod_dir, incflags, bcl_neuron_version = _bcl_cache_inputs()
    cache_key = compute_cache_key(mod_dir, bundled_mod_dir, incflags, bcl_neuron_version)
    cache_path = get_compilation_cache_path(cache_key)
    cache_ready = cache_path / READY_MARKER_FILE_NAME

    if cache_ready.exists():
        logger.debug(f"Compilation cache hit for hash {cache_key[:12]}")
        shutil.copytree(compiled_mechanisms_path(cache_path), compiled_path)
        return

    lock = FileLock(cache_path / "dir.lock")

    with lock.acquire(timeout=5 * 60):
        if cache_ready.exists():
            logger.debug(f"Compilation cache hit (after lock) for hash {cache_key[:12]}")
            shutil.copytree(compiled_mechanisms_path(cache_path), compiled_path)
            return

        logger.info(f"Compilation cache miss for hash {cache_key[:12]}, compiling")

        libnrnmech = _bcl_compile_mods([mod_dir] if mod_dir.is_dir() else [], cache_path)

        cache_ready.touch()

    # libnrnmech is <arch>/lib/nrnmech.<so|dylib>; its grandparent is the
    # architecture directory nrnivmodl produced for this machine.
    shutil.copytree(libnrnmech.parent.parent, compiled_path)
