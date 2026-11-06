import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from app.core.lfp_summary import summary
from app.core.lfp_summary.summary import (
    MAX_OVERVIEW_STEPS,
    STATS,
    WELCH_MAX_SEGMENT,
    Centred,
    NotSummarisableError,
    OverMemoryError,
    contact_stats,
    correlation,
    overview_level,
    peak_bytes,
    sum_report,
    verify,
    welch,
    write_summary,
)
from app.domains.simulation_result.lfp_summary import NoSummaryReason
from tests.core.lfp_summary.utils import local_reader, write_report


class TestSumReport(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = self.dir / "lfp.h5"

    def summed(self, **kwargs):
        read, size = local_reader(self.path)
        return sum_report(read, size, **kwargs)

    def test_the_total_over_the_cells_in_uv(self):
        expected = write_report(self.path, cells=5, contacts=3, steps=40)

        report = self.summed()

        np.testing.assert_allclose(report.total, expected, rtol=1e-6)
        self.assertEqual(report.populations, ["pop"])
        self.assertEqual((report.start, report.dt), (0.0, 0.1))

    def test_blocks_of_rows_read_in_parallel(self):
        expected = write_report(self.path, cells=4, contacts=2, steps=101)

        # A row is 32 bytes: blocks of 3 rows, the last one shorter
        with patch.object(summary, "BLOCK_BYTES", 96):
            report = self.summed(workers=4)

        np.testing.assert_allclose(report.total, expected, rtol=1e-6)

    def test_every_population_is_added(self):
        expected = write_report(self.path, populations=("a", "b"))

        report = self.summed()

        np.testing.assert_allclose(report.total, expected, rtol=1e-6)
        self.assertEqual(report.populations, ["a", "b"])

    def test_a_chunked_report_is_read_through_h5py(self):
        expected = write_report(self.path, chunked=True)

        report = self.summed()

        np.testing.assert_allclose(report.total, expected, rtol=1e-6)

    def test_units_other_than_volts(self):
        expected = write_report(self.path, units="mV")

        np.testing.assert_allclose(self.summed().total, expected, rtol=1e-6)

    def test_contacts_not_in_order(self):
        write_report(self.path, cells=2, contacts=3, steps=5)
        with h5py.File(self.path, "r+") as f:
            g = f["report/pop"]
            data = g["data"][:]
            g["mapping/element_ids"][...] = np.array([2, 1, 0, 0, 1, 2], np.uint32)
        expected = np.zeros((5, 3))
        for column, contact in enumerate([2, 1, 0, 0, 1, 2]):
            expected[:, contact] += data[:, column] * 1e6

        np.testing.assert_allclose(self.summed().total, expected, rtol=1e-6)

    def test_not_a_report(self):
        cases = {
            "not hdf5": lambda: self.path.write_bytes(b"not an h5 file at all" * 100),
            "no report": lambda: h5py.File(self.path, "w").close(),
        }
        for name, make in cases.items():
            with self.subTest(name):
                make()
                with self.assertRaises(NotSummarisableError) as caught:
                    self.summed()
                self.assertEqual(caught.exception.reason, NoSummaryReason.NOT_LFP_REPORT)

    def test_unknown_units(self):
        write_report(self.path)
        with h5py.File(self.path, "r+") as f:
            f["report/pop/data"].attrs["units"] = "furlongs"

        with self.assertRaises(NotSummarisableError) as caught:
            self.summed()

        self.assertEqual(caught.exception.reason, NoSummaryReason.UNREADABLE)

    def test_malformed_reports_are_unreadable(self):
        def edit(change):
            def make():
                write_report(self.path)
                with h5py.File(self.path, "r+") as f:
                    change(f["report/pop"])

            return make

        def replace(group, name, value):
            del group[name]
            group[name] = value

        cases = {
            "more columns than element ids": edit(
                lambda g: replace(g, "mapping/element_ids", np.arange(5, dtype=np.uint32))
            ),
            "negative element ids": edit(
                lambda g: replace(g, "mapping/element_ids", -np.ones(12, dtype=np.int64))
            ),
            "a time without its step": edit(
                lambda g: replace(g, "mapping/time", np.array([0.0, 5.0]))
            ),
            "a step of zero": edit(lambda g: replace(g, "mapping/time", np.array([0.0, 5.0, 0.0]))),
            "no steps": edit(lambda g: replace(g, "data", np.zeros((0, 12), np.float32))),
        }
        for name, make in cases.items():
            with self.subTest(name):
                make()
                with self.assertRaises(NotSummarisableError) as caught:
                    self.summed()
                self.assertEqual(caught.exception.reason, NoSummaryReason.UNREADABLE)

    def test_values_that_are_not_finite_are_unreadable(self):
        for value in (np.nan, np.inf):
            with self.subTest(value=value):
                write_report(self.path)
                with h5py.File(self.path, "r+") as f:
                    f["report/pop/data"][3, 1] = value

                with self.assertRaises(NotSummarisableError) as caught:
                    self.summed()

                self.assertEqual(caught.exception.reason, NoSummaryReason.UNREADABLE)

    def test_units_missing_are_unreadable(self):
        write_report(self.path)
        with h5py.File(self.path, "r+") as f:
            del f["report/pop/data"].attrs["units"]

        with self.assertRaises(NotSummarisableError) as caught:
            self.summed()

        self.assertEqual(caught.exception.reason, NoSummaryReason.UNREADABLE)

    def test_a_summary_over_the_memory_given(self):
        write_report(self.path, contacts=4, steps=50)

        with self.assertRaises(OverMemoryError):
            self.summed(memory=peak_bytes(50, 4) - 1)
        self.summed(memory=peak_bytes(50, 4))

    def test_a_total_over_the_memory_cap(self):
        write_report(self.path, contacts=4, steps=50)

        with (
            patch.object(summary, "MAX_TOTAL_BYTES", 50 * 4 * 8 - 1),
            self.assertRaises(NotSummarisableError) as caught,
        ):
            self.summed()

        self.assertEqual(caught.exception.reason, NoSummaryReason.TOO_LARGE)


class TestTheNumbers(unittest.TestCase):
    def test_the_spectrum_of_a_sine(self):
        dt_ms = 0.025
        t = np.arange(40_000) * dt_ms / 1000
        x = (3 * np.sin(2 * np.pi * 40 * t))[:, None, None]

        psd, frequencies = welch(x, dt_ms)

        bin_hz = frequencies[1] - frequencies[0]
        self.assertLessEqual(abs(frequencies[psd[0, 0].argmax()] - 40), bin_hz)
        # Parseval: the density sums to the variance
        np.testing.assert_allclose(psd[0, 0].sum() * bin_hz, x.var(), rtol=0.01)

    def test_a_long_run_keeps_the_segment_small(self):
        steps = WELCH_MAX_SEGMENT * 8
        x = np.zeros((steps, 1, 1), np.float32)

        psd, frequencies = welch(x, 0.025)

        self.assertEqual(len(frequencies), WELCH_MAX_SEGMENT // 2 + 1)
        self.assertEqual(psd.shape, (1, 1, WELCH_MAX_SEGMENT // 2 + 1))

    def test_the_stats_of_a_contact(self):
        x = np.array([1.0, -3.0, 2.0, 0.0])[:, None, None]

        stats = dict(zip(STATS, contact_stats(x, start=10.0, dt=0.5)[0, 0], strict=True))

        self.assertEqual((stats["min"], stats["max"], stats["ptp"]), (-3, 2, 5))
        self.assertEqual(stats["mean"], 0)
        self.assertAlmostEqual(float(stats["rms"]), np.sqrt(14 / 4), places=5)
        self.assertEqual(stats["trough_ms"], 10.5)

    def test_the_overview_level_is_where_the_bins_get_under_the_size(self):
        self.assertEqual(overview_level(MAX_OVERVIEW_STEPS), 0)
        self.assertEqual(overview_level(MAX_OVERVIEW_STEPS + 1), 1)
        self.assertEqual(overview_level(30_000), 4)

    def test_correlation(self):
        a = np.array([1.0, -1.0, 2.0, -2.0])
        total = np.stack([a, -a, 2 * a, np.zeros(4)], axis=1)

        c = correlation(Centred.of(total))

        self.assertEqual(list(c[0, :3]), [32767, -32767, 32767])
        # A silent contact has no correlation to give
        self.assertEqual(c[0, 3], 0)


class TestWriteSummary(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def summarise(self, steps: int):
        report_path = self.dir / "lfp.h5"
        expected = write_report(report_path, cells=2, contacts=3, steps=steps)
        read, size = local_reader(report_path)
        h5_path = self.dir / "summary.h5"
        index = write_summary(
            sum_report(read, size), h5_path, version=1, source={"asset_id": "a", "size": size}
        )
        return expected, h5_path, index

    def test_every_dataset_lies_at_its_offset(self):
        _, h5_path, index = self.summarise(steps=50)

        verify(h5_path, index)
        json.dumps(index)

    def test_the_index(self):
        _, _, index = self.summarise(steps=50)

        self.assertEqual((index["format"], index["version"]), ("lfp-summary", 1))
        self.assertEqual(index["time"], {"start": 0.0, "dt": 0.1, "steps": 50})
        self.assertEqual(index["contacts"], 3)
        self.assertEqual([a["name"] for a in index["axes"]], ["total"])
        self.assertEqual(
            index["axes"][0]["levels"],
            [{"step": 1, "kind": "value", "dataset": "/lfp/total/level0"}],
        )

    def test_level0_is_the_total_to_its_scale(self):
        expected, h5_path, index = self.summarise(steps=50)

        with h5py.File(h5_path, "r") as h5:
            level0 = h5["lfp/total/level0"][0]
        scale = index["axes"][0]["scales"][0]
        np.testing.assert_allclose(level0.T * scale, expected, atol=scale)

    def test_a_long_run_has_its_rows_in_chunks_and_one_level_of_min_and_max(self):
        expected, h5_path, index = self.summarise(steps=MAX_OVERVIEW_STEPS * 2 + 1)

        # 2,049 bins of 2 steps are too many, 1,025 of 4 are not
        self.assertEqual(
            index["axes"][0]["levels"],
            [
                {
                    "step": 1,
                    "kind": "value",
                    "dataset": "/lfp/total/level0",
                    "chunks": "/lfp/total/chunks",
                },
                {"step": 4, "kind": "min_max", "dataset": "/lfp/total/level2"},
            ],
        )
        self.assertNotIn("/lfp/total/level0", index["datasets"])
        self.assertEqual(index["datasets"]["/lfp/total/level2"]["shape"], [1, 3, 1025, 2])
        verify(h5_path, index)
        with h5py.File(h5_path, "r") as h5:
            rows = h5["lfp/total/level0"][0]
            overview = h5["lfp/total/level2"][0]
        scale = index["axes"][0]["scales"][0]
        np.testing.assert_allclose(rows.T * scale, expected, atol=scale)
        np.testing.assert_array_equal(overview[1, 1], [rows[1, 4:8].min(), rows[1, 4:8].max()])
        # The last bin is the one step left over
        np.testing.assert_array_equal(overview[2, -1], [rows[2, -1], rows[2, -1]])

    def test_the_correlation_is_on_the_total_alone(self):
        _, h5_path, index = self.summarise(steps=50)

        stored = index["axes"][0]["correlation"]
        self.assertEqual(index["datasets"][stored["dataset"]]["shape"], [1, 3, 3])
        self.assertNotIn("correlation", index)
        with h5py.File(h5_path, "r") as h5:
            self.assertEqual(round(h5[stored["dataset"]][0, 1, 1] * stored["scale"], 3), 1)
