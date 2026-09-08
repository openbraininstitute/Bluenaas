"""NEURON's process-wide setup.

NEURON keeps one mechanism table per process and fills it while the module is
imported, reading ./x86_64 relative to the current directory at that moment. With
the wrong import order or working directory the mechanisms a template needs stay
undefined, and NEURON segfaults as soon as bluecellulab instantiates that template.
Passing the model path to load_mechanisms drops both conditions.

Callers that build a Cell call load() first and wrap the instantiation in
capture_init_errors().
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loguru import logger

from app.core.compilation_cache import compiled_mechanisms_path
from app.core.exceptions import SingleNeuronAssetError, SingleNeuronInitError
from app.utils.neuron_output import capture_neuron_output, neuron_error_summary

_loaded: Path | None = None


def load(model_path: Path) -> None:
    """Import NEURON and register the mechanisms compiled for this model."""
    global _loaded

    if _loaded is not None:
        if _loaded != model_path:
            raise RuntimeError(
                f"NEURON holds the mechanisms of {_loaded} and cannot take {model_path} as well"
            )
        return

    mechanisms = compiled_mechanisms_path(model_path)

    # NEURON prints a banner and a DISPLAY warning on import. Callers show captured
    # NEURON output to the user, so keep the startup noise out of it.
    with capture_neuron_output() as startup_output:
        import bluecellulab  # noqa: F401
        from neuron import load_mechanisms

        # compile_with_cache runs nrnivmodl only for a model that ships .mod files,
        # so a missing directory means the model uses NEURON's built-ins.
        loaded = not mechanisms.is_dir() or load_mechanisms(str(model_path))

    if not loaded:
        raise SingleNeuronAssetError(
            f"NEURON loaded no mechanisms from {mechanisms}",
            details=startup_output.getvalue() or None,
        )

    _loaded = model_path


@contextmanager
def capture_init_errors() -> Iterator[None]:
    """Turn a failed Cell instantiation into an error carrying NEURON's own wording.

    NEURON prints the reason it rejected a model instead of putting it in the
    exception, so the printed block travels on the raised error as ``details``. A
    failure that printed nothing propagates unchanged.

    Wrap the instantiation only. load() belongs outside, so an asset failure keeps
    its own type.
    """
    with capture_neuron_output() as neuron_output:
        try:
            yield

        except Exception as ex:
            captured = neuron_output.getvalue()

            # NEURON prints before it gives up, so silence means the failure was ours:
            # a missing file, an unreadable directory.
            if not captured:
                raise

            raise SingleNeuronInitError(
                neuron_error_summary(ex, captured), details=captured
            ) from ex

    # Warnings NEURON printed on a successful instantiation would be lost otherwise.
    captured = neuron_output.getvalue()
    if captured:
        logger.debug("NEURON output during model init:\n{}", captured)
