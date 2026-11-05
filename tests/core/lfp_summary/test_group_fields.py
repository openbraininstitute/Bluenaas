import json
import shutil
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
from loguru import logger

from app.core.lfp_summary import summary
from app.core.lfp_summary.nodes import cell_labels
from app.core.lfp_summary.summary import (
    MAX_OVERVIEW_STEPS,
    PSD_BANDS,
    GroupFields,
    OverMemoryError,
    SummedReport,
    deflated_row,
    log_bands,
    mean_level,
    peak_bytes,
    sum_report,
    verify,
    write_summary,
)
from tests.core.lfp_summary.utils import local_reader, write_nodes, write_report


def labels_from(columns: dict[str, dict[str, np.ndarray]]):
    return lambda population, node_ids: {
        axis: labels[node_ids] for axis, labels in columns.get(population, {}).items()
    }


def fields_of(path: Path, population: str = "pop") -> np.ndarray:
    """The report's data as steps x cells x contacts, in uV."""
    with h5py.File(path, "r") as f:
        cells = f[f"report/{population}/mapping/node_ids"].shape[0]
        data = f[f"report/{population}/data"][:]
    return data.reshape(data.shape[0], cells, -1).astype(np.float64) * 1e6


class TestReadProgress(unittest.TestCase):
    def setUp(self):
        self.messages: list[str] = []
        sink = logger.add(self.messages.append, format="{message}")
        self.addCleanup(logger.remove, sink)
        patcher = patch.object(summary.time, "monotonic")
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)
        self.clock.return_value = 0.0
        self.progress = summary.ReadProgress("a", 100_000_000_000)

    def test_how_far_how_fast_and_how_long_left(self):
        self.clock.return_value = 60.0
        self.progress.add(6_000_000_000)

        self.assertEqual(
            self.messages,
            [
                "LFP report a: read 6.0 of 100.0 GB (6%), 100 MB/s, 100 MB/s on average,"
                " about 16 min left\n"
            ],
        )

    def test_the_speed_is_of_the_last_stretch_beside_the_average(self):
        self.clock.return_value = 60.0
        self.progress.add(6_000_000_000)
        self.clock.return_value = 120.0
        self.progress.add(3_000_000_000)

        self.assertIn("50 MB/s, 75 MB/s on average", self.messages[1])

    def test_no_more_often_than_it_should(self):
        self.clock.return_value = summary.PROGRESS_LOG_SECONDS - 1
        self.progress.add(1_000_000)

        self.assertEqual(self.messages, [])

    def test_the_read_in_all(self):
        self.progress.add(100_000_000_000)
        self.clock.return_value = 1000.0
        self.progress.finish()

        self.assertEqual(
            self.messages, ["LFP report a: read 100.0 GB in 17 min, 100 MB/s on average\n"]
        )


class TestCellLabels(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = self.dir / "nodes.h5"

    def labels(self, population="pop", node_ids=(2, 0)):
        read, size = local_reader(self.path)
        return cell_labels(read, size, population, np.array(node_ids))

    def test_a_column_through_its_library_for_the_cells_asked(self):
        write_nodes(self.path, "pop", {"mtype": ["A", "B", "C"]})

        self.assertEqual(self.labels()["mtype"].tolist(), ["C", "A"])

    def test_a_column_of_numbers_as_text(self):
        write_nodes(self.path, "pop", {"layer": [1, 2, 3]})

        self.assertEqual(self.labels()["layer"].tolist(), ["3", "1"])

    def test_only_the_columns_it_splits_by(self):
        write_nodes(self.path, "pop", {"mtype": ["A", "B", "C"], "morphology": ["x", "y", "z"]})

        self.assertEqual(list(self.labels()), ["mtype"])

    def test_a_population_not_in_the_file(self):
        write_nodes(self.path, "other", {"mtype": ["A", "B", "C"]})

        self.assertEqual(self.labels(), {})


class TestSumByGroup(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = self.dir / "lfp.h5"

    def summed(self, labels, **kwargs):
        read, size = local_reader(self.path)
        return sum_report(read, size, labels_of=labels_from(labels), **kwargs)

    def test_each_group_is_the_sum_of_its_cells(self):
        write_report(self.path, cells=4, contacts=3, steps=20)
        cells = fields_of(self.path)

        report = self.summed({"pop": {"mtype": np.array(["B", "A", "B", "A"])}})

        field = report.fields["mtype"]
        self.assertEqual(field.groups, ["A", "B"])
        np.testing.assert_allclose(field.values[:, 0], cells[:, [1, 3]].sum(1), rtol=1e-4)
        np.testing.assert_allclose(field.values[:, 1], cells[:, [0, 2]].sum(1), rtol=1e-4)

    def test_groups_add_up_to_the_total_on_every_axis(self):
        write_report(self.path, cells=6, contacts=3, steps=20)

        report = self.summed(
            {
                "pop": {
                    "mtype": np.array(["a", "b", "c", "a", "b", "c"]),
                    "etype": np.array(["x", "x", "y", "y", "x", "y"]),
                }
            }
        )

        self.assertEqual(list(report.fields), ["mtype", "etype"])
        for field in report.fields.values():
            np.testing.assert_allclose(field.values.sum(1), report.total, atol=1e-3)

    def test_populations_share_the_groups_of_an_axis(self):
        write_report(self.path, cells=2, contacts=2, steps=10, populations=("a", "b"))
        first, second = fields_of(self.path, "a"), fields_of(self.path, "b")

        report = self.summed(
            {
                # Node ids of b start at 2
                "a": {"mtype": np.array(["L", "M"])},
                "b": {"mtype": np.array(["", "", "M", "N"])},
            }
        )

        field = report.fields["mtype"]
        self.assertEqual(field.groups, ["L", "M", "N"])
        np.testing.assert_allclose(field.values[:, 0], first[:, 0], rtol=1e-4)
        np.testing.assert_allclose(field.values[:, 1], first[:, 1] + second[:, 0], rtol=1e-4)
        np.testing.assert_allclose(field.values[:, 2], second[:, 1], rtol=1e-4)

    def test_an_axis_one_population_lacks_is_left_out(self):
        write_report(self.path, cells=2, contacts=2, steps=10, populations=("a", "b"))

        report = self.summed({"a": {"mtype": np.array(["L", "M"])}, "b": {}})

        self.assertEqual(report.fields, {})

    def test_an_axis_the_cells_do_not_differ_on_is_left_out(self):
        write_report(self.path, cells=2, contacts=2, steps=10)

        report = self.summed({"pop": {"layer": np.array(["5", "5"])}})

        self.assertEqual(report.fields, {})

    def test_cells_not_on_every_contact_in_order_have_no_groups(self):
        write_report(self.path, cells=2, contacts=3, steps=5)
        with h5py.File(self.path, "r+") as f:
            f["report/pop/mapping/element_ids"][...] = np.array([2, 1, 0, 0, 1, 2], np.uint32)

        report = self.summed({"pop": {"mtype": np.array(["A", "B"])}})

        self.assertEqual(report.fields, {})

    def test_groups_over_the_memory_move_a_build_that_can(self):
        write_report(self.path, cells=2, contacts=4, steps=50)

        with self.assertRaises(OverMemoryError):
            self.summed(
                {"pop": {"mtype": np.array(["A", "B"])}},
                memory=peak_bytes(50, 4),
                move_for_groups=True,
            )

    def test_groups_over_the_memory_are_left_out_largest_first(self):
        write_report(self.path, cells=3, contacts=4, steps=50)
        labels = {
            "pop": {
                "mtype": np.array(["A", "B", "C"]),
                "etype": np.array(["x", "y", "y"]),
            }
        }

        report = self.summed(labels, memory=peak_bytes(50, 4, 2))

        self.assertEqual(list(report.fields), ["etype"])

    def test_the_sum_is_the_same_across_blocks(self):
        write_report(self.path, cells=4, contacts=2, steps=101)
        cells = fields_of(self.path)

        # A row is 32 bytes: blocks of 3 rows, the last one shorter
        with patch.object(summary, "BLOCK_BYTES", 96):
            report = self.summed({"pop": {"mtype": np.array(["A", "A", "B", "B"])}}, workers=4)

        np.testing.assert_allclose(
            report.fields["mtype"].values[:, 0], cells[:, :2].sum(1), rtol=1e-4
        )


class TestTheNumbers(unittest.TestCase):
    def test_means_with_a_shorter_last_bin(self):
        rows = np.array([[1, 3, 10, 20, 7]], np.int16)

        np.testing.assert_array_equal(mean_level(rows, 1), [[2, 15, 7]])

    def test_a_short_spectrum_is_left_as_it_is(self):
        frequencies = np.arange(PSD_BANDS + 1.0)
        psd = np.ones((2, PSD_BANDS + 1), np.float32)

        bands, centres = log_bands(psd, frequencies)

        self.assertIs(bands, psd)
        self.assertIs(centres, frequencies)

    def test_bands_keep_the_level_of_a_flat_spectrum(self):
        frequencies = np.arange(4097.0)
        psd = np.full((1, 4097), 3.0, np.float32)

        bands, centres = log_bands(psd, frequencies)

        self.assertLessEqual(len(centres), PSD_BANDS)
        self.assertEqual(bands.shape, (1, len(centres)))
        np.testing.assert_allclose(bands, 3.0)
        self.assertGreater(centres[0], 0)
        self.assertTrue((np.diff(centres) > 0).all())
        self.assertLessEqual(centres[-1], 4096)

    def test_a_deflated_row_is_what_hdf5_filters_undo(self):
        row = np.array([1, -2, 300, -32768, 32767], np.int16)

        shuffled = np.frombuffer(zlib.decompress(deflated_row(row)), np.uint8)

        # Low bytes first, then high bytes
        np.testing.assert_array_equal(
            shuffled.reshape(2, -1).T.ravel().view("<i2"),
            row,
        )


class TestWriteGroupFields(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.h5_path = self.dir / "summary.h5"

    def summarise(self, steps: int, contacts: int = 3):
        rng = np.random.default_rng(1)
        t = np.arange(steps)[:, None, None]
        values = (rng.normal(0, 5, (steps, 2, contacts)) + 20 * np.sin(t / 50)).astype(np.float32)
        report = SummedReport(
            populations=["pop"],
            start=100.0,
            dt=0.1,
            total=values.sum(1, dtype=np.float64),
            fields={"mtype": GroupFields(["A", "B"], values)},
        )
        index = write_summary(report, self.h5_path, version=2, source={"asset_id": "a"})
        return values, index

    def axis(self, index) -> dict:
        return next(a for a in index["axes"] if a["name"] == "mtype")

    def test_every_dataset_and_chunk_lies_where_the_index_says(self):
        _, index = self.summarise(steps=MAX_OVERVIEW_STEPS * 2 + 1)

        verify(self.h5_path, index)
        json.dumps(index)

    def test_a_long_run_has_compressed_rows_and_a_level_of_means(self):
        values, index = self.summarise(steps=MAX_OVERVIEW_STEPS * 4)

        axis = self.axis(index)
        self.assertEqual(
            axis["levels"],
            [
                {
                    "step": 1,
                    "kind": "value",
                    "dataset": "/lfp/mtype/level0",
                    "chunks": "/lfp/mtype/chunks",
                },
                {"step": 4, "kind": "mean", "dataset": "/lfp/mtype/level2"},
            ],
        )
        self.assertNotIn("/lfp/mtype/level0", index["datasets"])
        self.assertEqual(
            index["datasets"]["/lfp/mtype/level2"]["shape"], [2, 3, MAX_OVERVIEW_STEPS]
        )
        self.assertEqual(index["datasets"]["/lfp/mtype/chunks"]["shape"], [2, 3, 2])
        self.assertEqual(index["datasets"]["/lfp/mtype/chunks"]["dtype"], "<u8")
        with h5py.File(self.h5_path, "r") as h5:
            self.assertEqual(h5["lfp/mtype/level0"].chunks, (1, 1, MAX_OVERVIEW_STEPS * 4))
            row = h5["lfp/mtype/level0"][1, 2]
            means = h5["lfp/mtype/level2"][1, 2]
        scale = axis["scales"][1]
        np.testing.assert_allclose(row * scale, values[:, 1, 2], atol=scale)
        np.testing.assert_allclose(
            means * scale, values[:, 1, 2].reshape(-1, 4).mean(1), atol=scale
        )

    def test_a_run_under_the_overview_size_is_plain_and_whole(self):
        values, index = self.summarise(steps=50)

        axis = self.axis(index)
        self.assertEqual(
            axis["levels"], [{"step": 1, "kind": "value", "dataset": "/lfp/mtype/level0"}]
        )
        self.assertEqual(index["datasets"]["/lfp/mtype/level0"]["shape"], [2, 3, 50])
        self.assertNotIn("/lfp/mtype/chunks", index["datasets"])
        verify(self.h5_path, index)
        with h5py.File(self.h5_path, "r") as h5:
            row = h5["lfp/mtype/level0"][0, 1]
        scale = axis["scales"][0]
        np.testing.assert_allclose(row * scale, values[:, 0, 1], atol=scale)

    def test_a_silent_group_is_written_and_read_back(self):
        values = np.zeros((MAX_OVERVIEW_STEPS * 2, 2, 2), np.float32)
        values[:, 1] = 1.0
        report = SummedReport(
            populations=["pop"],
            start=0.0,
            dt=0.1,
            total=values.sum(1, dtype=np.float64),
            fields={"mtype": GroupFields(["A", "B"], values)},
        )

        index = write_summary(report, self.h5_path, version=2, source={})

        verify(self.h5_path, index)

    def test_spectra_per_axis_and_in_bands_for_groups(self):
        _, index = self.summarise(steps=MAX_OVERVIEW_STEPS * 4)

        axis = self.axis(index)
        total = next(a for a in index["axes"] if a["name"] == "total")
        self.assertNotIn("psd_frequencies", index)
        self.assertEqual(total["psd_frequencies"][0], 0)
        self.assertGreater(axis["psd_frequencies"][0], 0)
        self.assertLessEqual(len(axis["psd_frequencies"]), PSD_BANDS)
        self.assertEqual(
            index["datasets"]["/lfp/mtype/psd"]["shape"], [2, 3, len(axis["psd_frequencies"])]
        )

    def test_shares_of_the_total_add_up_to_one(self):
        _, index = self.summarise(steps=200)

        self.assertAlmostEqual(sum(self.axis(index)["shares"]), 1.0, places=4)

    def test_no_copy_of_the_report(self):
        _, _ = self.summarise(steps=50)

        with h5py.File(self.h5_path, "r") as h5:
            self.assertNotIn("report", h5)
