"""Owns NEURON's process-wide setup.

NEURON keeps one mechanism table per process and fills it while the module is
imported, reading ./x86_64 relative to the current directory at that moment. Get
the import order or the current directory wrong and the mechanisms a template
needs stay undefined, which segfaults NEURON as soon as bluecellulab instantiates
that template. Passing the model path to load_mechanisms drops both conditions.

Everything that builds a Cell calls load() first, and wraps the instantiation
itself in capture_init_errors().
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

    # NEURON prints a banner and a DISPLAY warning while it starts up. Callers show
    # captured NEURON output to the user, so keep the startup noise out of it.
    with capture_neuron_output() as startup_output:
        import bluecellulab  # noqa: F401
        from neuron import load_mechanisms

        # compile_with_cache runs nrnivmodl only for a model that ships .mod files,
        # so a missing directory means the model needs the built-in mechanisms.
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

    NEURON prints the reason it refused a model rather than putting it in the
    exception, so the printed block is captured and travels on the raised error as
    ``details``. Every path that builds a Cell wraps it in this, so a simulation and
    a compatibility check explain a mismatch the same way.

    Only failures NEURON reported become an incompatibility. Anything that fails
    without printing propagates unchanged.

    Wrap the instantiation alone. load() belongs outside, so an asset failure stays
    an asset failure instead of being relabelled an incompatibility.
    """
    with capture_neuron_output() as neuron_output:
        try:
            yield

        except Exception as ex:
            captured = neuron_output.getvalue()

            # NEURON prints before it gives up, so silence means the failure was ours:
            # a missing file, an unreadable directory. Caching that as an incompatibility
            # would record a verdict about the models that we never reached.
            if not captured:
                raise

            raise SingleNeuronInitError(
                neuron_error_summary(ex, captured), details=captured
            ) from ex

    # Capturing would otherwise silently drop the warnings NEURON prints on an
    # otherwise successful instantiation.
    captured = neuron_output.getvalue()
    if captured:
        logger.debug("NEURON output during model init:\n{}", captured)
