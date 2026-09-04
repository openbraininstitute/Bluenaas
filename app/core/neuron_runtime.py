"""Owns NEURON's process-wide setup.

NEURON keeps one mechanism table per process and fills it while the module is
imported, reading ./x86_64 relative to the current directory at that moment. Get
the import order or the current directory wrong and the mechanisms a template
needs stay undefined, which segfaults NEURON as soon as bluecellulab instantiates
that template. Passing the model path to load_mechanisms drops both conditions.

Everything that builds a Cell calls load() first.
"""

from pathlib import Path

from app.core.exceptions import SingleNeuronAssetError
from app.utils.neuron_output import capture_neuron_output

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

    mechanisms = model_path / "x86_64"

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
