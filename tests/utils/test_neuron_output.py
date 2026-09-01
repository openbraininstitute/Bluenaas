import os
import unittest

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.utils.neuron_output import (
    MAX_OUTPUT_LENGTH,
    capture_neuron_output,
    neuron_error_summary,
    scrub_neuron_output,
)


class TestCaptureNeuronOutput(unittest.TestCase):
    """Drives real NEURON with a synthetic template — no model assets needed."""

    @classmethod
    def setUpClass(cls):
        from neuron import h

        cls.h = h
        h("""
            begintemplate CompatTestBoom
            proc init() {
                execerror("Less than three axon sections are present!", \
"This emodel can't be run with such a morphology!")
            }
            endtemplate CompatTestBoom
        """)

    def test_captures_hoc_error_block(self):
        with capture_neuron_output() as output:
            with self.assertRaises(RuntimeError):
                self.h.CompatTestBoom()

        self.assertIn("Less than three axon sections are present!", output.text)
        self.assertIn("This emodel can't be run with such a morphology!", output.text)

    def test_captures_failures_that_print_without_raising(self):
        # h.load_file returns 0 rather than raising, so the printed line is the only
        # evidence that anything went wrong.
        with capture_neuron_output() as output:
            self.assertEqual(self.h.load_file("compat_test_missing.hoc"), 0.0)

        self.assertIn("Couldn't find", output.text)

    def test_summary_strips_hoc_call_machinery(self):
        with capture_neuron_output() as output:
            with self.assertRaises(RuntimeError) as ctx:
                self.h.CompatTestBoom()

        summary = neuron_error_summary(ctx.exception, output.text)

        self.assertTrue(summary.startswith("Less than three axon sections"), summary)
        self.assertNotIn("hocobj_call", summary)
        self.assertNotIn("hoc_execerror", summary)


class TestNeuronErrorSummary(unittest.TestCase):
    def test_falls_back_to_printed_line_when_exception_is_silent(self):
        summary = neuron_error_summary(
            RuntimeError(""), "NEURON: Couldn't find: cell.hoc\n near line 0\n"
        )
        self.assertEqual(summary, "Couldn't find: cell.hoc")

    def test_falls_back_to_type_name_when_nothing_is_available(self):
        self.assertEqual(neuron_error_summary(RuntimeError("")), "RuntimeError")


class TestScrubNeuronOutput(unittest.TestCase):
    def test_replaces_container_paths_with_basenames(self):
        scrubbed = scrub_neuron_output(
            "NEURON: Couldn't find: /app/storage/single-neuron/model-candidate/ab/cd/hoc/cell.hoc"
        )
        self.assertEqual(scrubbed, "NEURON: Couldn't find: cell.hoc")

    def test_drops_the_uuid_suffix_bluecellulab_appends_to_templates(self):
        scrubbed = scrub_neuron_output(
            "        cADpyr_bluecellulab_0123456789abcdef0123456789abcdef[0].replace_axon()"
        )
        self.assertEqual(scrubbed, "cADpyr[0].replace_axon()")

    def test_drops_empty_source_context(self):
        scrubbed = scrub_neuron_output("NEURON: boom\n near line 0\n \n ^\n        boom()\n")
        self.assertEqual(scrubbed, "NEURON: boom\n        boom()")

    def test_keeps_real_source_context(self):
        scrubbed = scrub_neuron_output("NEURON: boom\n near line 42\n  bad_call()\n")
        self.assertIn("near line 42", scrubbed)

    def test_truncates_runaway_output(self):
        scrubbed = scrub_neuron_output("x" * (MAX_OUTPUT_LENGTH * 2))

        self.assertLess(len(scrubbed), MAX_OUTPUT_LENGTH + 100)
        self.assertTrue(scrubbed.endswith("(truncated)"))


if __name__ == "__main__":
    unittest.main()
