from celery import Task

from bluenaas.infrastructure.celery.worker_scalability import EcsTaskProtection
from bluenaas.utils.run_on_env import run_on_env


class BluenaasTask(Task):
    track_started = True

    def __init__(self):
        self.task_protection = EcsTaskProtection()
        super().__init__()

    def before_start(self, task_id, args, kwargs):
        # TODO: create a draft nexus simulation
        super().before_start(task_id, args, kwargs)
        run_on_env(
            env_fns={
                "production": self.task_protection.toggle_protection,
            },
            is_protected=True,
        )

    def on_success(self, retval, task_id, args, kwargs):
        # TODO: save simulation to nexus
        run_on_env(
            env_fns={
                "production": self.task_protection.extend_protection,
            },
            ets=5,
        )

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # TODO: save the failure in nexus too
        super().on_failure(exc, task_id, args, kwargs, einfo)
        run_on_env(
            env_fns={
                "production": self.task_protection.extend_protection,
            },
            ets=5,
        )
