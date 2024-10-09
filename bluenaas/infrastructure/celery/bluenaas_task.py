from celery import Task
from loguru import logger


class BluenaasTask(Task):
    def __init__(self):
        # self.task_protection = EcsTaskProtection()
        super().__init__()

    def before_start(self, task_id, args, kwargs):
        # TODO: create a draft nexus simulation
        super().before_start(task_id, args, kwargs)
        # TODO: uncomment for aws
        # self.task_protection.toggle_protection(True)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"@@on_success {(task_id)}")
        # TODO: save simulation to nexus
        # TODO: uncomment for aws
        # self.task_protection.toggle_protection(False)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.info(f"@@on_failure {(exc, task_id, args, kwargs, einfo)}")
        # TODO: save the failure in nexus too
        super().on_failure(exc, task_id, args, kwargs, einfo)
        # TODO: uncomment for aws
        # self.task_protection.toggle_protection(False)
