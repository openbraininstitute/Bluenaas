"""Capture and scrub what NEURON prints while a model is instantiated.

Embedded in Python, NEURON prints through ``sys.stdout`` and ``sys.stderr``, so
``contextlib.redirect_*`` catches it. Loguru still reaches the real stderr, because
``setup_logging`` binds the stream object up front.

Some hoc failures only print: ``h.load_file`` on a missing file returns 0 with
``NEURON: Couldn't find: ...``. Failures that raise also print the hoc call stack
their message drops.
"""

import io
import re
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Iterator

MAX_OUTPUT_LENGTH = 4000

# Scrubbing drops lines before it truncates, so capture keeps headroom above
# MAX_OUTPUT_LENGTH.
MAX_CAPTURE_LENGTH = 4 * MAX_OUTPUT_LENGTH

# "hocobj_call error: hoc_execerror: <the message we want>"
_HOC_ERROR_PREFIX = re.compile(r"^(?:hocobj_call error:\s*)?(?:hoc_execerror:\s*)?")

# The lookbehind skips URLs and relative paths.
_ABSOLUTE_PATH = re.compile(r"(?<![\w:/.])/(?:[\w.-]+/)+([\w.-]+)")

# NeuronTemplate.load() appends a uuid to each template name.
_TEMPLATE_SUFFIX = re.compile(r"_bluecellulab_[0-9a-f]{32}")

# NEURON's source context for template errors, which have no line to point at.
_EMPTY_SOURCE_CONTEXT = re.compile(r"^\s*(?:near line 0|\^)\s*$")


class _BoundedBuffer(io.StringIO):
    """Drops everything past ``MAX_CAPTURE_LENGTH``.

    A ``printf`` per segment in a mod file can print megabytes.
    """

    def write(self, s: str) -> int:
        remaining = MAX_CAPTURE_LENGTH - self.tell()

        if remaining > 0:
            super().write(s[:remaining])

        # NEURON's print hook does not handle a short write, so report the full length.
        return len(s)


@contextmanager
def capture_neuron_output() -> Iterator[io.StringIO]:
    """Collect stdout and stderr in one buffer, in the order NEURON printed them.

    The redirect covers the whole process, so keep threads out of the block.
    capture_init_errors() reads anything they print as NEURON rejecting the model,
    and the compatibility check caches that.
    """
    buffer = _BoundedBuffer()

    with redirect_stdout(buffer), redirect_stderr(buffer):
        yield buffer


def scrub_neuron_output(text: str | None) -> str | None:
    """Strip container paths and NEURON bookkeeping from output shown to a user."""
    if not text:
        return None

    lines = []

    for line in text.splitlines():
        if _EMPTY_SOURCE_CONTEXT.match(line):
            continue

        line = _ABSOLUTE_PATH.sub(r"\1", line)
        line = _TEMPLATE_SUFFIX.sub("", line)
        line = line.rstrip()

        if not line:
            continue

        lines.append(line)

    scrubbed = "\n".join(lines).strip()

    if len(scrubbed) > MAX_OUTPUT_LENGTH:
        scrubbed = f"{scrubbed[:MAX_OUTPUT_LENGTH].rstrip()}\n… (truncated)"

    return scrubbed or None


def neuron_error_summary(exception: BaseException, captured: str = "") -> str:
    """One line on why NEURON gave up, preferring the hoc error, which the model author wrote."""
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
