import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from rq.job import JobStatus

from app.infrastructure import rq as rq_module
from app.infrastructure.rq import get_picked_up_job_ids, get_unfinished_job_ids


def fake_queue(name: str, started: list[str], intermediate: list[str]):
    return SimpleNamespace(
        name=name,
        started_job_registry=SimpleNamespace(get_job_ids=lambda: started),
        intermediate_queue=SimpleNamespace(get_job_ids=lambda: intermediate),
    )


def fake_job(job_id: str, status: JobStatus, func_name: str = "app.some.job"):
    return SimpleNamespace(id=job_id, func_name=func_name, get_status=lambda refresh=True: status)


class TestGetPickedUpJobIds(unittest.TestCase):
    def run_with(self, queues, jobs, known_queues=None, exclude_func_names=()):
        with (
            patch.object(rq_module.Queue, "all", return_value=queues),
            patch.object(rq_module, "_queues", known_queues or {}),
            patch.object(
                rq_module.Job,
                "fetch_many",
                side_effect=lambda ids, **kw: [jobs.get(i) for i in ids],
            ),
        ):
            return get_picked_up_job_ids(exclude_func_names=exclude_func_names)

    def test_jobs_started_and_jobs_taken_from_the_queue_but_not_yet_started_count(self):
        queues = [fake_queue("high", ["running"], ["in-transit"]), fake_queue("low", ["long"], [])]
        jobs = {
            "running": fake_job("running", JobStatus.STARTED),
            "in-transit": fake_job("in-transit", JobStatus.QUEUED),
            "long": fake_job("long", JobStatus.STARTED),
        }

        self.assertEqual(self.run_with(queues, jobs), {"running", "in-transit", "long"})

    def test_a_job_in_both_places_is_counted_once(self):
        queues = [fake_queue("high", ["a"], ["a"])]

        self.assertEqual(self.run_with(queues, {"a": fake_job("a", JobStatus.STARTED)}), {"a"})

    def test_finished_and_vanished_jobs_do_not_count(self):
        queues = [fake_queue("high", ["done", "failed", "gone"], [])]
        jobs = {
            "done": fake_job("done", JobStatus.FINISHED),
            "failed": fake_job("failed", JobStatus.FAILED),
        }

        self.assertEqual(self.run_with(queues, jobs), set())

    def test_excluded_functions_do_not_count(self):
        queues = [fake_queue("medium", ["cleanup", "sim"], [])]
        jobs = {
            "cleanup": fake_job("cleanup", JobStatus.STARTED, "app.job.handlers.admin.cache.clear"),
            "sim": fake_job("sim", JobStatus.STARTED),
        }

        result = self.run_with(
            queues, jobs, exclude_func_names={"app.job.handlers.admin.cache.clear"}
        )

        self.assertEqual(result, {"sim"})

    def test_a_job_whose_record_cannot_be_read_still_counts(self):
        class UnreadableJob:
            id = "broken"

            @property
            def func_name(self):
                raise ValueError("cannot unpickle")

            def get_status(self, refresh=True):
                return JobStatus.STARTED

        queues = [fake_queue("high", ["broken"], [])]

        result = self.run_with(queues, {"broken": UnreadableJob()}, exclude_func_names={"x"})

        self.assertEqual(result, {"broken"})

    def test_queues_this_service_knows_are_checked_even_if_redis_does_not_list_them(self):
        known = {"low": fake_queue("low", ["only-known"], [])}
        jobs = {"only-known": fake_job("only-known", JobStatus.STARTED)}

        self.assertEqual(self.run_with([], jobs, known_queues=known), {"only-known"})


class TestGetUnfinishedJobIds(unittest.TestCase):
    def test_only_jobs_that_exist_and_have_not_finished(self):
        jobs = {
            "started": fake_job("started", JobStatus.STARTED),
            "queued": fake_job("queued", JobStatus.QUEUED),
            "finished": fake_job("finished", JobStatus.FINISHED),
            "stopped": fake_job("stopped", JobStatus.STOPPED),
            "canceled": fake_job("canceled", JobStatus.CANCELED),
            "failed": fake_job("failed", JobStatus.FAILED),
        }
        ids = [*jobs, "expired"]

        with patch.object(
            rq_module.Job, "fetch_many", side_effect=lambda i, **kw: [jobs.get(x) for x in i]
        ):
            self.assertEqual(get_unfinished_job_ids(ids), {"started", "queued"})


if __name__ == "__main__":
    unittest.main()
