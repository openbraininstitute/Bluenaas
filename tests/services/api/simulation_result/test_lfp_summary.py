import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from entitysdk.common import ProjectContext
from entitysdk.exception import EntitySDKError
from entitysdk.models import SimulationResult
from entitysdk.types import AssetLabel
from entitysdk.utils.http import HTTPStatusError, RequestError
from rq.job import JobStatus

from app.constants import READY_MARKER_FILE_NAME
from app.core.exceptions import AppError
from app.domains.simulation_result.lfp_summary import (
    GroupsUnavailable,
    LfpSummaryState,
    NoSummaryReason,
)
from app.infrastructure.rq import JobQueue, get_queue
from app.infrastructure.storage import lfp_summary as storage
from app.infrastructure.storage.lfp_summary import (
    FAILED_BUILD_TTL,
    MAX_REPORT_BYTES,
    SMALL_REPORT_BYTES,
    SUMMARY_FILE_NAME,
    SummaryInfo,
    build_job_id,
    enqueue_build,
    write_no_summary,
    write_summary_info,
)
from app.services.api.simulation_result import lfp_summary as service
from tests.infrastructure.storage.lfp_summary_case import LfpSummaryTestCase, report_of

URL = "https://bucket.s3/report.h5?signature"
NODES_URL = "https://bucket.s3/nodes.h5?signature"


class TestLfpSummaryStatus(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.result_id = uuid4()
        patcher = patch.object(service, "_download_url", return_value=URL)
        self.download_url = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(service, "_lfp_report", return_value=service.LfpReport(False))
        self.is_lfp_report = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(
            service, "_nodes_urls", return_value=service.NodesFiles({"pop": NODES_URL})
        )
        self.nodes_urls = patcher.start()
        self.addCleanup(patcher.stop)

    def status_of(self, report):
        # In a thread, as the route runs it
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(
                service._get_or_build_summary,
                self.result_id,
                uuid4(),
                report,
                access_token="token",
                project_context=self.project_context,
                later=lambda task: task(),
            ).result()

    def job_of(self, report, queue: JobQueue):
        return get_queue(queue).fetch_job(build_job_id(self.epoch(), report.id, queue))

    def test_ready(self):
        report = report_of(100)
        directory = self.summary_dir_of(report.id)
        write_summary_info(directory, SummaryInfo(size=12, sha256="abc"))
        (directory / READY_MARKER_FILE_NAME).touch()

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.READY)
        self.assertEqual((status.size, status.sha256), (12, "abc"))
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_refused_by_its_marker(self):
        report = report_of(100)
        write_no_summary(self.summary_dir_of(report.id), NoSummaryReason.UNREADABLE, "units")

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.REFUSED)
        self.assertEqual(status.reason, NoSummaryReason.UNREADABLE)

    def test_refused_without_a_job(self):
        for report, reason in [
            (report_of(100, AssetLabel.spike_report), NoSummaryReason.NOT_LFP_REPORT),
            (report_of(100, is_directory=True), NoSummaryReason.NOT_LFP_REPORT),
            (report_of(MAX_REPORT_BYTES + 1), NoSummaryReason.TOO_LARGE),
        ]:
            with self.subTest(reason=reason):
                status = self.status_of(report)

                self.assertEqual(status.state, LfpSummaryState.REFUSED)
                self.assertEqual(status.reason, reason)
                self.assertEqual(self.queued_ids(JobQueue.LOW), [])
                self.assertEqual(self.queued_ids(JobQueue.CPU4_MEM16), [])

    def test_a_report_labelled_as_voltages_is_summarised(self):
        report = report_of(100, AssetLabel.voltage_report)

        self.assertEqual(self.status_of(report).state, LfpSummaryState.BUILDING)

    def test_the_queue_is_chosen_by_the_report_size(self):
        for size, queue in [
            (1, JobQueue.LOW),
            (SMALL_REPORT_BYTES, JobQueue.LOW),
            (SMALL_REPORT_BYTES + 1, JobQueue.CPU4_MEM16),
            (MAX_REPORT_BYTES, JobQueue.CPU4_MEM16),
        ]:
            with self.subTest(size=size):
                report = report_of(size)

                status = self.status_of(report)

                self.assertEqual(status.state, LfpSummaryState.BUILDING)
                self.assertIn(build_job_id(self.epoch(), report.id, queue), self.queued_ids(queue))

    def test_the_job_queued(self):
        report = report_of(100)

        self.status_of(report)

        job = self.job_of(report, JobQueue.LOW)
        self.assertEqual(job.kwargs["asset_id"], report.id)
        self.assertEqual(job.kwargs["epoch"], self.epoch())
        self.assertEqual(job.kwargs["queue"], "low")
        self.assertNotIn(URL, job.description)
        self.assertEqual(job.kwargs["url"], URL)
        self.assertEqual(job.kwargs["size"], 100)
        self.assertEqual(job.kwargs["nodes"], {"pop": NODES_URL})
        self.assertIsNone(job.kwargs["groups_unavailable"])
        self.assertFalse(job.kwargs["regroup"])
        self.assertNotIn(NODES_URL, job.description)
        self.assertEqual(job.retries_left, 1)
        self.assertEqual(job.failure_ttl, FAILED_BUILD_TTL)
        self.assertEqual(
            job.failure_callback,
            storage.remove_build_leftovers,  # type: ignore[attr-defined]
        )

    def test_no_second_job_while_one_is_queued(self):
        report = report_of(100)
        self.status_of(report)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.BUILDING)
        self.assertEqual(status.queue_position, 0)
        self.assertEqual(len(self.queued_ids(JobQueue.LOW)), 1)
        self.assertEqual(self.download_url.call_count, 1)

    def test_a_voltage_report_that_is_no_lfp_is_refused(self):
        self.is_lfp_report.return_value = None

        status = self.status_of(report_of(100, AssetLabel.voltage_report))

        self.assertEqual(status.state, LfpSummaryState.REFUSED)
        self.assertEqual(status.reason, NoSummaryReason.NOT_LFP_REPORT)
        self.assertEqual(self.queued_ids(JobQueue.LOW), [])

    def test_a_job_moved_to_the_larger_queue_is_building(self):
        report = report_of(100)
        self.status_of(report)
        self.job_of(report, JobQueue.LOW).set_status(JobStatus.FINISHED)
        enqueue_build(
            JobQueue.CPU4_MEM16, epoch=self.epoch(), asset_id=report.id, url=URL, size=100, nodes={}
        )

        self.assertEqual(self.status_of(report).state, LfpSummaryState.BUILDING)
        self.assertEqual(self.job_of(report, JobQueue.LOW).get_status(), JobStatus.FINISHED)

    def test_a_finished_job_without_a_summary_is_queued_again_with_a_new_url(self):
        report = report_of(100)
        self.status_of(report)
        job = self.job_of(report, JobQueue.LOW)
        get_queue(JobQueue.LOW).remove(job)
        job.set_status(JobStatus.FINISHED)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.BUILDING)
        self.assertEqual(self.job_of(report, JobQueue.LOW).get_status(), JobStatus.QUEUED)
        self.assertEqual(self.download_url.call_count, 2)

    def test_failed_after_its_retry(self):
        report = report_of(100)
        self.status_of(report)
        self.job_of(report, JobQueue.LOW).set_status(JobStatus.FAILED)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.FAILED)

    def test_a_summed_report_is_built_without_its_cells_groups(self):
        self.is_lfp_report.return_value = service.LfpReport(summed=True)
        report = report_of(100)

        self.status_of(report)

        self.nodes_urls.assert_not_called()
        self.assertEqual(self.job_of(report, JobQueue.LOW).kwargs["nodes"], {})

    def test_the_job_says_why_there_are_no_groups(self):
        self.nodes_urls.return_value = service.NodesFiles(
            {}, GroupsUnavailable.CIRCUIT_NOT_READABLE
        )
        report = report_of(100)

        self.status_of(report)

        job = self.job_of(report, JobQueue.LOW)
        self.assertEqual(job.kwargs["groups_unavailable"], "circuit_not_readable")

    def ready_without_groups(self, report, why: GroupsUnavailable | None):
        directory = self.summary_dir_of(report.id)
        write_summary_info(directory, SummaryInfo(size=12, sha256="abc", groups_unavailable=why))
        (directory / READY_MARKER_FILE_NAME).touch()

    def regroup_job_of(self, report):
        return get_queue(JobQueue.LOW).fetch_job(
            build_job_id(self.epoch(), report.id, JobQueue.LOW, regroup=True)
        )

    def test_a_summary_without_groups_for_the_report_itself_is_left(self):
        report = report_of(100)
        self.ready_without_groups(report, None)

        self.assertEqual(self.status_of(report).state, LfpSummaryState.READY)

        self.nodes_urls.assert_not_called()

    def test_a_user_who_can_read_the_circuit_has_the_groups_built(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)

        status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.READY)
        job = self.regroup_job_of(report)
        self.assertTrue(job.kwargs["regroup"])
        self.assertEqual(job.kwargs["nodes"], {"pop": NODES_URL})
        self.assertEqual(job.kwargs["url"], URL)

    def test_a_summed_report_is_not_grouped_by_one_who_can_read_its_circuit(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.is_lfp_report.return_value = service.LfpReport(summed=True)

        self.assertEqual(self.status_of(report).state, LfpSummaryState.READY)

        self.nodes_urls.assert_not_called()
        self.assertIsNone(self.regroup_job_of(report))

    def test_a_user_who_can_not_read_it_either_builds_nothing(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.nodes_urls.return_value = service.NodesFiles(
            {}, GroupsUnavailable.CIRCUIT_NOT_READABLE
        )

        self.assertEqual(self.status_of(report).state, LfpSummaryState.READY)

        self.assertIsNone(self.regroup_job_of(report))

    def test_the_circuit_is_not_asked_for_again_while_its_groups_are_built(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.status_of(report)
        # Failed too: it is kept, and tried again only once it has gone
        self.regroup_job_of(report).set_status(JobStatus.FAILED)

        self.status_of(report)

        self.assertEqual(self.nodes_urls.call_count, 1)

    def test_a_regroup_that_finished_does_not_hold_back_another(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.status_of(report)
        self.regroup_job_of(report).set_status(JobStatus.FINISHED)

        self.status_of(report)

        self.assertEqual(self.nodes_urls.call_count, 2)

    def test_a_circuit_that_can_be_read_but_has_no_groups_has_the_summary_built_again(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.nodes_urls.return_value = service.NodesFiles({})

        self.status_of(report)

        self.assertEqual(self.regroup_job_of(report).kwargs["nodes"], {})

    def test_entitycore_failing_does_not_fail_a_summary_ready_to_read(self):
        report = report_of(100)
        self.ready_without_groups(report, GroupsUnavailable.CIRCUIT_NOT_READABLE)
        self.nodes_urls.side_effect = EntitySDKError("failed")

        self.assertEqual(self.status_of(report).state, LfpSummaryState.READY)

        self.assertIsNone(self.regroup_job_of(report))

    def test_a_new_format_version_is_built_again(self):
        report = report_of(100)
        directory = self.summary_dir_of(report.id)
        write_summary_info(directory, SummaryInfo(size=12, sha256="abc"))
        (directory / READY_MARKER_FILE_NAME).touch()

        with patch.object(storage, "FORMAT_VERSION", storage.FORMAT_VERSION + 1):
            status = self.status_of(report)

        self.assertEqual(status.state, LfpSummaryState.BUILDING)


class TestGetReport(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        service.access_found.clear()
        self.addCleanup(service.access_found.clear)
        self.result_id = uuid4()
        self.report = report_of(100)
        self.result = SimpleNamespace(assets=[self.report])
        patcher = patch.object(service, "user_client")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(service, "get_entity_or_not_found", return_value=self.result)
        self.get_entity = patcher.start()
        self.addCleanup(patcher.stop)

    def auth(self, token: str = "token", expires_in: float = 3600):
        return SimpleNamespace(
            access_token=token,
            decoded_token=SimpleNamespace(exp=int(time.time() + expires_in)),
        )

    def get(self, auth=None, project_context=None):
        return service._get_report(
            self.result_id,
            self.report.id,
            auth=auth or self.auth(),
            project_context=project_context or self.project_context,
        )

    def test_access_found_is_kept_for_the_reads_that_follow(self):
        for _ in range(3):
            self.assertEqual(self.get(), (self.result, self.report))

        self.assertEqual(self.get_entity.call_count, 1)

    def test_kept_per_user_and_project(self):
        self.get()
        self.get(auth=self.auth("another"))
        self.get(project_context=ProjectContext(project_id=uuid4(), virtual_lab_id=uuid4()))

        self.assertEqual(self.get_entity.call_count, 3)

    def test_asked_again_once_it_is_old(self):
        self.get()

        later = time.monotonic() + service.ACCESS_SECONDS + 1
        with patch.object(service.time, "monotonic", return_value=later):
            self.get()

        self.assertEqual(self.get_entity.call_count, 2)

    def test_not_kept_past_the_token(self):
        self.get(auth=self.auth(expires_in=-1))
        self.get(auth=self.auth(expires_in=-1))

        self.assertEqual(self.get_entity.call_count, 2)

    def test_no_access_is_not_kept(self):
        self.get_entity.side_effect = AppError(
            message="no", error_code=None, http_status_code=HTTPStatus.NOT_FOUND
        )

        for _ in range(2):
            with self.assertRaises(AppError):
                self.get()

        self.assertEqual(self.get_entity.call_count, 2)


class TestIsLfpReport(LfpSummaryTestCase):
    def is_lfp(self, report, reports: object, config: bool = True) -> bool:
        return self.is_lfp_with(report, json.dumps({"reports": reports}).encode(), config)

    def is_lfp_with(self, report, content: bytes, config: bool = True) -> bool:
        return self.lfp_report_with(report, content, config) is not None

    def lfp_report_with(self, report, content: bytes, config: bool = True):
        client = MagicMock()
        config_asset = SimpleNamespace(id=uuid4(), label=AssetLabel.sonata_simulation_config)
        simulation = SimpleNamespace(assets=[config_asset] if config else [])
        client.get_entity.side_effect = [simulation]
        client.download_content.return_value = content
        with patch.object(service, "user_client", return_value=client):
            return service._lfp_report(
                uuid4(), report, access_token="token", project_context=self.project_context
            )

    def voltage_report(self, path: str):
        return SimpleNamespace(label=AssetLabel.voltage_report, path=path)

    def test_an_lfp_report_by_its_label(self):
        self.assertTrue(self.is_lfp(report_of(100), None, config=False))

    def test_a_voltage_report_by_its_sonata_type(self):
        for path, reports, expected in [
            ("output/lfp.h5", {"lfp": {"type": "lfp"}}, True),
            ("lfp.H5", {"lfp": {"type": "lfp"}}, True),
            ("soma.h5", {"soma": {"type": "compartment"}, "lfp": {"type": "lfp"}}, False),
            ("other.h5", {"lfp": {"type": "lfp"}}, False),
            ("lfp.h5", None, False),
        ]:
            with self.subTest(path=path, reports=reports):
                self.assertEqual(self.is_lfp(self.voltage_report(path), reports), expected)

    def test_a_malformed_config_is_no_lfp(self):
        report = self.voltage_report("lfp.h5")
        for content in [b"not json", b"[]", b"{}", b'{"reports": []}']:
            with self.subTest(content=content):
                self.assertFalse(self.is_lfp_with(report, content))

    def test_a_simulation_without_a_config(self):
        self.assertFalse(self.is_lfp(self.voltage_report("lfp.h5"), {}, config=False))

    def test_a_summed_report_by_its_method(self):
        for report, entry, summed in [
            (self.voltage_report("lfp.h5"), {"type": "lfp", "method": "sum"}, True),
            (self.voltage_report("lfp.h5"), {"type": "lfp", "method": "by_cell"}, False),
            (self.voltage_report("lfp.h5"), {"type": "lfp"}, False),
            (SimpleNamespace(label=AssetLabel.lfp_report, path="lfp.h5"), {"method": "sum"}, True),
        ]:
            with self.subTest(entry=entry):
                content = json.dumps({"reports": {"lfp": entry}}).encode()
                self.assertEqual(self.lfp_report_with(report, content), service.LfpReport(summed))

    def test_an_lfp_report_by_its_label_whose_simulation_is_not_found(self):
        client = MagicMock()
        client.get_entity.side_effect = AppError(
            message="no", error_code=None, http_status_code=HTTPStatus.NOT_FOUND
        )
        with patch.object(service, "user_client", return_value=client):
            lfp = service._lfp_report(
                uuid4(), report_of(100), access_token="token", project_context=self.project_context
            )
        self.assertEqual(lfp, service.LfpReport(summed=False))


class TestDownloadUrl(LfpSummaryTestCase):
    def url_answered_by(self, response: httpx.Response, asset_path: str | None = None) -> str:
        with patch.object(service.httpx, "get", return_value=response) as get:
            url = service._download_url(
                SimulationResult,
                uuid4(),
                uuid4(),
                access_token="token",
                project_context=self.project_context,
                asset_path=asset_path,
            )
        self.headers = get.call_args.kwargs["headers"]
        self.params = get.call_args.kwargs["params"]
        return url

    def test_the_redirect_of_the_download(self):
        response = httpx.Response(307, headers={"location": URL})

        self.assertEqual(self.url_answered_by(response), URL)
        self.assertEqual(self.headers["Authorization"], "Bearer token")
        self.assertEqual(self.headers["project-id"], str(self.project_context.project_id))
        self.assertIsNone(self.params)

    def test_a_file_within_a_directory_asset(self):
        response = httpx.Response(307, headers={"location": URL})

        self.assertEqual(self.url_answered_by(response, asset_path="pop/nodes.h5"), URL)
        self.assertEqual(self.params, {"asset_path": "pop/nodes.h5"})

    def test_the_download_not_answered(self):
        with (
            patch.object(service.httpx, "get", side_effect=httpx.ConnectTimeout("late")),
            self.assertRaises(AppError) as caught,
        ):
            service._download_url(
                SimulationResult,
                uuid4(),
                uuid4(),
                access_token="token",
                project_context=self.project_context,
            )

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.BAD_GATEWAY)

    def test_no_such_file(self):
        with self.assertRaises(AppError) as caught:
            self.url_answered_by(httpx.Response(404))

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.NOT_FOUND)

    def test_no_redirect(self):
        with self.assertRaises(AppError) as caught:
            self.url_answered_by(httpx.Response(200, content=b"the file"))

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.BAD_GATEWAY)


class TestNodesFiles(unittest.TestCase):
    def config(self, *networks, manifest=None):
        return {"manifest": manifest or {"$BASE_DIR": "./"}, "networks": {"nodes": list(networks)}}

    def network(self, path, **populations):
        return {"nodes_file": path, "populations": populations}

    def test_the_manifest_is_expanded_within_the_asset(self):
        config = self.config(
            self.network("$BASE_DIR/pop/nodes.h5", pop={"type": "biophysical"}),
        )

        self.assertEqual(service.nodes_files(config), {"pop": "pop/nodes.h5"})

    def test_a_manifest_of_several_steps(self):
        config = self.config(
            self.network("$NETWORK/nodes.h5", pop={}),
            manifest={"$BASE_DIR": ".", "$NETWORK": "$BASE_DIR/network"},
        )

        self.assertEqual(service.nodes_files(config), {"pop": "network/nodes.h5"})

    def test_virtual_populations_report_no_field(self):
        config = self.config(
            self.network("a/nodes.h5", a={"type": "biophysical"}),
            self.network("b/nodes.h5", b={"type": "virtual"}),
        )

        self.assertEqual(service.nodes_files(config), {"a": "a/nodes.h5"})

    def test_files_outside_the_asset_are_left_out(self):
        for path in ("/data/nodes.h5", "../nodes.h5", "$UNKNOWN/nodes.h5"):
            with self.subTest(path=path):
                config = self.config(self.network(path, pop={}))

                self.assertEqual(service.nodes_files(config), {})


class TestNodesUrls(LfpSummaryTestCase):
    def setUp(self):
        super().setUp()
        self.client = MagicMock()
        self.asset = SimpleNamespace(id=uuid4(), label=AssetLabel.sonata_circuit, is_directory=True)
        self.circuit = SimpleNamespace(id=uuid4(), assets=[self.asset])
        self.client.get_entity.side_effect = [
            SimpleNamespace(entity_id=self.circuit.id),
            self.circuit,
        ]
        self.client.download_content.return_value = json.dumps(
            {
                "manifest": {"$BASE_DIR": "./"},
                "networks": {
                    "nodes": [
                        {
                            "nodes_file": "$BASE_DIR/nodes.h5",
                            "populations": {"a": {}, "b": {}},
                        }
                    ]
                },
            }
        ).encode()
        patcher = patch.object(service, "user_client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(service, "_download_url", return_value=NODES_URL)
        self.download_url = patcher.start()
        self.addCleanup(patcher.stop)

    def nodes(self):
        return service._nodes_urls(
            uuid4(), access_token="token", project_context=self.project_context
        )

    def urls(self):
        return self.nodes().urls

    def test_a_url_per_population_and_one_per_file(self):
        self.assertEqual(self.urls(), {"a": NODES_URL, "b": NODES_URL})

        self.assertEqual(self.download_url.call_count, 1)
        self.assertEqual(self.download_url.call_args.kwargs["asset_path"], "nodes.h5")

    def test_the_config_is_read_from_the_circuits_directory(self):
        self.urls()

        self.assertEqual(
            self.client.download_content.call_args.kwargs["asset_path"], "circuit_config.json"
        )

    def test_a_circuit_without_its_sonata_directory(self):
        self.circuit.assets = []

        self.assertEqual(self.urls(), {})

    def test_a_simulation_of_something_else(self):
        self.client.get_entity.side_effect = [
            SimpleNamespace(entity_id=uuid4()),
            EntitySDKError("not a circuit"),
        ]

        self.assertEqual(self.urls(), {})

    def test_a_malformed_config(self):
        for content in (b"not json", b"[]", b"{}", b'{"networks": {"nodes": [{}]}}'):
            with self.subTest(content=content):
                self.client.get_entity.side_effect = [
                    SimpleNamespace(entity_id=self.circuit.id),
                    self.circuit,
                ]
                self.client.download_content.return_value = content

                self.assertEqual(self.urls(), {})

    def test_a_nodes_file_that_is_not_there(self):
        self.download_url.side_effect = AppError(
            message="no", error_code=None, http_status_code=HTTPStatus.NOT_FOUND
        )

        self.assertEqual(self.urls(), {})

    def test_a_nodes_url_not_given_just_now_is_not_taken_for_no_groups(self):
        self.download_url.side_effect = AppError(
            message="no", error_code=None, http_status_code=HTTPStatus.BAD_GATEWAY
        )

        with self.assertRaises(AppError):
            self.urls()

    def sdk_error(self, cause: Exception) -> EntitySDKError:
        error = EntitySDKError("failed")
        error.__cause__ = cause
        return error

    def status_error(self, status: int) -> HTTPStatusError:
        return HTTPStatusError(
            "failed", request=MagicMock(), response=MagicMock(status_code=status)
        )

    def test_entitycore_failing_to_answer_is_not_taken_for_no_groups(self):
        for cause in (RequestError("late"), self.status_error(503)):
            with self.subTest(cause=cause):
                self.client.get_entity.side_effect = [
                    SimpleNamespace(entity_id=self.circuit.id),
                    self.circuit,
                ]
                self.client.download_content.side_effect = self.sdk_error(cause)

                with self.assertRaises(EntitySDKError):
                    self.urls()

    def test_a_circuit_config_that_is_not_there(self):
        self.client.download_content.side_effect = self.sdk_error(self.status_error(404))

        self.assertEqual(self.nodes(), service.NodesFiles({}))

    def test_a_circuit_the_user_can_not_read(self):
        for status in (403, 404):
            with self.subTest(status=status):
                self.client.get_entity.side_effect = [
                    SimpleNamespace(entity_id=self.circuit.id),
                    self.sdk_error(self.status_error(status)),
                ]

                self.assertEqual(
                    self.nodes(),
                    service.NodesFiles({}, GroupsUnavailable.CIRCUIT_NOT_READABLE),
                )

    def test_a_circuit_entitycore_fails_to_give_is_not_taken_for_unreadable(self):
        self.client.get_entity.side_effect = [
            SimpleNamespace(entity_id=self.circuit.id),
            self.sdk_error(self.status_error(503)),
        ]

        with self.assertRaises(EntitySDKError):
            self.nodes()


class TestSummaryFile(LfpSummaryTestCase):
    def build(self, asset_id) -> str:
        directory = self.summary_dir_of(asset_id)
        info = SummaryInfo(size=7, sha256="abc")
        info.path(directory, SUMMARY_FILE_NAME).write_bytes(b"summary")
        write_summary_info(directory, info)
        (directory / READY_MARKER_FILE_NAME).touch()
        return '"abc"'

    def test_if_match(self):
        asset_id = uuid4()
        etag = self.build(asset_id)

        for if_match, served in [
            (None, True),
            ("*", True),
            (etag, True),
            (f'"other", {etag}', True),
            ('"other"', False),
            ("abc", False),
        ]:
            with self.subTest(if_match=if_match):
                response = service._summary_file_response(
                    asset_id, SUMMARY_FILE_NAME, "application/x-hdf5", if_match
                )
                if served:
                    self.assertEqual(response.headers["etag"], etag)
                    self.assertEqual(response.headers["cache-control"], "private, no-cache")
                else:
                    self.assertEqual(response.status_code, HTTPStatus.PRECONDITION_FAILED)

    def test_not_built(self):
        with self.assertRaises(AppError) as caught:
            service._summary_file_response(uuid4(), SUMMARY_FILE_NAME, "application/x-hdf5", None)

        self.assertEqual(caught.exception.http_status_code, HTTPStatus.NOT_FOUND)
