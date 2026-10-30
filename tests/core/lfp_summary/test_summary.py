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
    NotSummarisableError,
    OverMemoryError,
    peak_bytes,
    sum_report,
    verify,
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

    def test_min_max_levels_over_the_overview_size(self):
        _, h5_path, index = self.summarise(steps=MAX_OVERVIEW_STEPS * 2 + 1)

        # 2,049 bins after one halving, 1,025 after two
        levels = index["axes"][0]["levels"]
        self.assertEqual([level["step"] for level in levels], [1, 2, 4])
        self.assertEqual(index["datasets"]["/lfp/total/level2"]["shape"], [1, 3, 1025, 2])
        verify(h5_path, index)

    def test_the_total_for_sonata_readers(self):
        expected, h5_path, _ = self.summarise(steps=50)

        with h5py.File(h5_path, "r") as h5:
            g = h5["report/pop"]
            np.testing.assert_allclose(g["data"][:], expected / 1e6, rtol=1e-6)
            self.assertEqual(list(g["mapping/node_ids"][:]), [0])
            self.assertEqual(list(g["mapping/index_pointers"][:]), [0, 3])
