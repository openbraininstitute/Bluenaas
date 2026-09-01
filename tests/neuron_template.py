"""A hoc template that fails init() the way an incompatible emodel does.

Registering a template is process-global in NEURON, so this module exists to make
that happen exactly once no matter how many test modules need it.
"""

from neuron import h

_PART_1 = "Less than three axon sections are present!"
_PART_2 = "This emodel can't be run with such a morphology!"

ERROR_MESSAGE = f"{_PART_1} {_PART_2}"

h(
    "begintemplate CompatTestBoom\n"
    "proc init() {\n"
    f'  execerror("{_PART_1}", "{_PART_2}")\n'
    "}\n"
    "endtemplate CompatTestBoom\n"
)


def raise_hoc_error() -> None:
    """Instantiate the template, which raises RuntimeError and prints a NEURON block."""
    h.CompatTestBoom()
