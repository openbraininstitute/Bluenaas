"""Capture and sanitise the diagnostics NEURON writes while a model is instantiated.

NEURON prints hoc errors and warnings through Python's ``sys.stdout`` / ``sys.stderr``
objects — it installs a print hook when embedded in Python — so plain
``contextlib.redirect_*`` intercepts them and no file-descriptor juggling is needed.
Loguru is unaffected because ``setup_logging`` binds the stream object up front, so
our own logs keep going to the real stderr instead of into the capture buffer.

Capturing matters even though most hoc failures also raise: some NEURON errors only
print (``h.load_file`` on a missing file returns 0 and writes ``NEURON: Couldn't
find: ...``), and the printed block carries the hoc call stack that the exception
message drops.
"""

import io
import re
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Iterator

# Cap what we keep, so a chatty failure cannot bloat the API response or the
# cached compatibility result on disk.
MAX_OUTPUT_LENGTH = 4000

# "hocobj_call error: hoc_execerror: <the message we actually want>"
_HOC_ERROR_PREFIX = re.compile(r"^(?:hocobj_call error:\s*)?(?:hoc_execerror:\s*)?")

# Absolute paths point at container storage and mean nothing to a user.
_ABSOLUTE_PATH = re.compile(r"/(?:[\w.-]+/)+([\w.-]+)")

# NeuronTemplate.load() appends a uuid to every template name to keep them unique.
_TEMPLATE_SUFFIX = re.compile(r"_bluecellulab_[0-9a-f]{32}")

# Source context NEURON emits for template errors, where there is no line to point at.
_EMPTY_SOURCE_CONTEXT = re.compile(r"^\s*(?:near line 0|\^)\s*$")


class NeuronOutput:
    """Accumulates whatever NEURON wrote while the capture was active."""

    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    @property
    def text(self) -> str:
        """Everything NEURON printed, stderr first, verbatim."""
        return "".join(part for part in (self.stderr.getvalue(), self.stdout.getvalue()) if part)


@contextmanager
def capture_neuron_output() -> Iterator[NeuronOutput]:
    """Collect NEURON's printed diagnostics for the duration of the block.

    The output is readable from inside the block too, which is what callers need
    when they want to attach it to the exception they are about to raise.
    """
    output = NeuronOutput()

    with redirect_stdout(output.stdout), redirect_stderr(output.stderr):
        yield output


def scrub_neuron_output(text: str) -> str:
    """Strip container paths and NEURON bookkeeping from output shown to a user."""
    lines = []

    for line in text.splitlines():
        if _EMPTY_SOURCE_CONTEXT.match(line):
            continue

        line = _ABSOLUTE_PATH.sub(r"\1", line)
        line = _TEMPLATE_SUFFIX.sub("", line)
        line = line.rstrip()

        # NEURON pads its blocks with blank lines and never uses them meaningfully;
        # dropping them keeps the details readable in a narrow panel. Each error block
        # still opens with its own "NEURON: " line.
        if not line:
            continue

        lines.append(line)

    scrubbed = "\n".join(lines).strip()

    if len(scrubbed) > MAX_OUTPUT_LENGTH:
        scrubbed = f"{scrubbed[:MAX_OUTPUT_LENGTH].rstrip()}\n… (truncated)"

    return scrubbed


def neuron_error_summary(exception: BaseException, captured: str = "") -> str:
    """A single human-readable line explaining why NEURON gave up.

    Prefers the exception message — for a hoc ``execerror`` it already carries the
    modeller's own wording, e.g. "Less than three axon sections are present! This
    emodel can't be run with such a morphology!" — and falls back to the printed
    ``NEURON:`` line for the failures that print without raising anything useful.
    """
    message = _HOC_ERROR_PREFIX.sub("", str(exception)).strip()

    if message:
        return _TEMPLATE_SUFFIX.sub("", message)

    for line in captured.splitlines():
        if line.startswith("NEURON: "):
            return _TEMPLATE_SUFFIX.sub("", line.removeprefix("NEURON: ").strip())

    return type(exception).__name__
