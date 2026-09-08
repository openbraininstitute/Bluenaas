"""Capture and sanitize the diagnostics NEURON writes while a model is instantiated.

Embedded in Python, NEURON prints hoc errors and warnings through ``sys.stdout`` and
``sys.stderr``, so ``contextlib.redirect_*`` intercepts them without any
file-descriptor juggling. Loguru keeps writing to the real stderr because
``setup_logging`` binds the stream object up front.

Most hoc failures raise as well, but not all: ``h.load_file`` on a missing file
returns 0 and only prints ``NEURON: Couldn't find: ...``. The printed block also
carries the hoc call stack that the exception message drops.
"""

import io
import re
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Iterator

# Keeps a verbose failure from bloating the API response and the cached
# compatibility result on disk.
MAX_OUTPUT_LENGTH = 4000

# Scrubbing drops blank lines and source context before MAX_OUTPUT_LENGTH applies,
# so the buffer needs headroom above it.
MAX_CAPTURE_LENGTH = 4 * MAX_OUTPUT_LENGTH

# "hocobj_call error: hoc_execerror: <the message we want>"
_HOC_ERROR_PREFIX = re.compile(r"^(?:hocobj_call error:\s*)?(?:hoc_execerror:\s*)?")

# Absolute paths point at container storage and mean nothing to a user. The lookbehind
# keeps the pattern out of URLs and relative paths.
_ABSOLUTE_PATH = re.compile(r"(?<![\w:/.])/(?:[\w.-]+/)+([\w.-]+)")

# NeuronTemplate.load() appends a uuid to every template name to keep them unique.
_TEMPLATE_SUFFIX = re.compile(r"_bluecellulab_[0-9a-f]{32}")

# Source context NEURON emits for template errors, where there is no line to point at.
_EMPTY_SOURCE_CONTEXT = re.compile(r"^\s*(?:near line 0|\^)\s*$")


class _BoundedBuffer(io.StringIO):
    """A ``StringIO`` that drops everything past ``MAX_CAPTURE_LENGTH``.

    Mod files decide how much NEURON prints, and a ``printf`` per segment reaches
    megabytes. Only the head of it reaches a user, so a long-lived worker has no
    reason to hold the rest.
    """

    def write(self, s: str) -> int:
        remaining = MAX_CAPTURE_LENGTH - self.tell()

        if remaining > 0:
            super().write(s[:remaining])

        # NEURON's print hook does not handle a short write, and the dropped tail is
        # intended.
        return len(s)


@contextmanager
def capture_neuron_output() -> Iterator[io.StringIO]:
    """Collect NEURON's printed diagnostics for the duration of the block.

    Both streams share one buffer, so the text keeps the order NEURON printed it in.
    """
    buffer = _BoundedBuffer()

    with redirect_stdout(buffer), redirect_stderr(buffer):
        yield buffer


def scrub_neuron_output(text: str | None) -> str | None:
    """Strip container paths and NEURON bookkeeping from output shown to a user.

    Returns ``None`` for anything that scrubs down to nothing, so a caller can assign
    the result straight to an optional field.
    """
    if not text:
        return None

    lines = []

    for line in text.splitlines():
        if _EMPTY_SOURCE_CONTEXT.match(line):
            continue

        line = _ABSOLUTE_PATH.sub(r"\1", line)
        line = _TEMPLATE_SUFFIX.sub("", line)
        line = line.rstrip()

        # NEURON pads its blocks with blank lines.
        if not line:
            continue

        lines.append(line)

    scrubbed = "\n".join(lines).strip()

    if len(scrubbed) > MAX_OUTPUT_LENGTH:
        scrubbed = f"{scrubbed[:MAX_OUTPUT_LENGTH].rstrip()}\n… (truncated)"

    return scrubbed or None


def neuron_error_summary(exception: BaseException, captured: str = "") -> str:
    """One human-readable line explaining why NEURON gave up.

    A hoc ``execerror`` already carries the model author's own wording, e.g. "Less than
    three axon sections are present! This emodel can't be run with such a
    morphology!", so the exception message wins. Failures that print without raising
    anything useful fall back to the printed ``NEURON:`` line.
    """
    summary = _HOC_ERROR_PREFIX.sub("", str(exception)).strip()

    if not summary:
        summary = next(
            (
                line.removeprefix("NEURON: ").strip()
                for line in captured.splitlines()
                if line.startswith("NEURON: ")
            ),
            type(exception).__name__,
        )

    return _TEMPLATE_SUFFIX.sub("", summary)
