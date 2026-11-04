"""NEURON's process-wide setup.

NEURON fills its one mechanism table per process on import, from ./x86_64 in the
current directory at that moment. With the wrong import order or working directory a
template's mechanisms stay undefined, and NEURON segfaults when bluecellulab
instantiates it. load_mechanisms with the model path depends on neither.
"""

from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loguru import logger

from app.constants import LIBNRNMECH_PATH
from app.core.compilation_cache import compiled_mechanisms_path
from app.core.exceptions import SingleNeuronAssetError, SingleNeuronInitError
from app.utils.neuron_output import capture_neuron_output, neuron_error_summary

_loaded: Path | None = None


def ensure_libnrnmech_loaded(libnrnmech_path: Path, load_dll: Callable[[str], None]) -> None:
    """Load a compiled mechanisms library unless NEURON already registered it.

    NEURON registers ``./<arch>/libnrnmech.*`` from the working directory during hoc
    initialisation, so a library at that location must not be loaded again: a second
    load aborts with ``The user defined name already exists: <mechanism>``.
    """
    if not libnrnmech_path.exists():
        logger.info(
            f"No compiled mechanisms at {libnrnmech_path}; using NEURON built-in mechanisms only"
        )
        return
    if libnrnmech_path.resolve() == (Path.cwd() / LIBNRNMECH_PATH).resolve():
        logger.info(f"Mechanisms already registered by NEURON from {libnrnmech_path}")
        return
    load_dll(str(libnrnmech_path))


def load(model_path: Path) -> None:
    """Import NEURON and register the mechanisms compiled for this model.

    A process takes one model. That works because the RQ Worker forks a process per
    job, so a switch to SimpleWorker would break it.
    """
    global _loaded

    if _loaded is not None:
        if _loaded != model_path:
            raise RuntimeError(
                f"NEURON holds the mechanisms of {_loaded} and cannot take {model_path} as well"
            )
        return

    mechanisms = compiled_mechanisms_path(model_path)

    # Importing here, before capture_init_errors(), keeps NEURON's banner and DISPLAY
    # warning out of an incompatibility's details.
    with capture_neuron_output() as startup_output:
        import bluecellulab  # noqa: F401
        from neuron import load_mechanisms

        # Only a model that ships .mod files gets the directory. The rest use NEURON's
        # built-ins.
        loaded = not mechanisms.is_dir() or load_mechanisms(str(model_path))

    if not loaded:
        raise SingleNeuronAssetError(
            f"NEURON loaded no mechanisms from {mechanisms}",
            details=startup_output.getvalue() or None,
        )

    _loaded = model_path


@contextmanager
def capture_init_errors() -> Iterator[None]:
    """Raise a failed instantiation as SingleNeuronInitError with NEURON's output as ``details``.

    Keep load() outside the block, so its asset errors keep their type.
    """
    with capture_neuron_output() as neuron_output:
        try:
            yield

        except Exception as ex:
            captured = neuron_output.getvalue()

            # NEURON prints before it rejects a model, so silence means the failure was
            # ours, like a missing file.
            if not captured:
                raise

            raise SingleNeuronInitError(
                neuron_error_summary(ex, captured), details=captured
            ) from ex

    captured = neuron_output.getvalue()
    if captured:
        logger.debug("NEURON output during model init:\n{}", captured)
