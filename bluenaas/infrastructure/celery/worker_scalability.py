import os
import time
from celery import Celery
from loguru import logger
import requests
from requests.adapters import Retry, HTTPAdapter
from bluenaas.config.settings import settings
from bluenaas.infrastructure.celery.aws import (
    get_cloudwatch_boto_client,
    get_ecs_boto_client,
)
from bluenaas.infrastructure.celery.events_manager import CeleryEventsManager
from bluenaas.infrastructure.celery.broker_manager import get_bulk_queues_depths

# NOTE: this global variable are just for testing/debugging
in_use_instances = 2


# NOTE: the work scalability is only when use the EC2 launch type
# NOTE: if Fargate is the way we go, then no need for scalability manager
class WorkerScalability:
    # NOTE: this should be env variables
    # NOTE: this is just test values, they are open for update after better requirements/tests
    # Number of tasks in queues to scale up workers.
    queue_depth_for_scale_up = settings.CELERY_QUEUE_DEPTH_FOR_SCALE_UP
    # Number of tasks in queues to scale down workers.
    queue_depth_for_scale_down = settings.CELERY_QUEUE_DEPTH_FOR_SCALE_DOWN
    # Minimum support workers ECS can launch
    min_ecs_tasks = settings.AWS_MIN_ECS_TASKS
    # Maximum support workers ECS can launch
    max_ecs_tasks = settings.AWS_MAX_ECS_TASKS

    def _get_ecs_task_status(self):
        client = get_ecs_boto_client()
        service_type = client.describe_services(
            cluster=settings.AWS_CLUSTER_NAME,
            services=[
                settings.AWS_SERVICE_NAME,
            ],
        )["services"][0]
        running_instances = service_type["runningCount"]
        pending_instances = service_type["pendingCount"]
        in_use_instances = running_instances + pending_instances

        return (
            running_instances,
            pending_instances,
            in_use_instances,
        )

    def _update_ecs_task(self, desired_count: int):
        """
        Update the ECS service with the new desired task count.

        If the service's desired task count is different from the current one,
        the service will be updated with the new desired count.

        :param desired_count: The number of tasks to set for the ECS service.
        """

        client = get_ecs_boto_client()
        try:
            service_type = client.describe_services(
                cluster=settings.AWS_CLUSTER_NAME,
                services=[
                    settings.AWS_SERVICE_NAME,
                ],
            )
            # logger.info(f'@@ [service_type]: {json.dumps(service_type, indent=4, default=str)}')
            if (
                service_type["services"]
                and service_type["services"][0]["desiredCount"] != desired_count
            ):
                logger.info(
                    f'updating service --> current desired: {service_type["services"][0]["desiredCount"]} '
                )
                client.update_service(
                    cluster=settings.AWS_CLUSTER_NAME,
                    service=settings.AWS_SERVICE_NAME,
                    desiredCount=desired_count,
                )
        except Exception as ex:
            logger.exception(f"update ecs cluster failed {ex}")

    def _scale_up_ecs_cluster(self, needed_instances: int):
        """
        Scales up the ECS service by the number of needed instances,
        ensuring that the total count does not exceed the maximum allowed tasks.

        :param needed_instances: The number of additional tasks required.
        :return: None
        """
        (running_instances, pending_instances, in_use_instances) = (
            self._get_ecs_task_status()
        )
        desired_instances = running_instances + needed_instances

        if desired_instances > self.max_ecs_tasks:
            desired_instances = self.max_ecs_tasks
        if in_use_instances <= desired_instances:
            self._update_ecs_task(
                desired_count=desired_instances,
            )

    def publish_queue_state_to_cloudwatch(
        self, queues_to_check: list[str], namespace: str
    ):
        cloudwatch = get_cloudwatch_boto_client()
        depths = get_bulk_queues_depths(queues_to_check)

        for q in depths:
            try:
                cloudwatch.put_metric_data(
                    Namespace=namespace,
                    MetricData=[
                        {
                            "MetricName": q,
                            "Value": int(depths[q]),
                            "Timestamp": time.time(),
                            "Unit": "Count",
                        }
                    ],
                )

            except Exception as e:
                logger.exception(f"Publishing queues state to cloudwatch failed {e}")

    def scale_down_workers(self):
        """
        Scale down ECS tasks if the queue depth is below or equal to the scale-down threshold.

        If the queue depth is zero or below the defined `queue_depth_for_scale_down`,
        and the running tasks is greater then the threshold
        the ECS tasks will be reduced to the minimum allowed task count.
        """
        # TODO: uncomment this for aws
        # (running_instances, pending_instances, in_use_instances) = self._get_ecs_task_status()
        q_depths = get_bulk_queues_depths()
        # global in_use_instances
        if in_use_instances > q_depths["total"] and (
            in_use_instances > self.min_ecs_tasks
        ):
            in_use_instances = q_depths["total"]
            # TODO: uncomment this for aws
            # self._update_ecs_task(q_depths["total"])
            pass
        if (
            q_depths["total"] == 0
            or q_depths["total"] <= self.queue_depth_for_scale_down
        ) and (in_use_instances > self.min_ecs_tasks):
            in_use_instances = self.min_ecs_tasks
            # TODO: uncomment this for aws
            # self._update_ecs_task(self.min_ecs_tasks)
            pass

    def scale_up_workers(self):
        """
        Scale up ECS tasks if the queue depth exceeds the threshold.

        If the queue depth exceeds `queue_depth_for_scale_up`, and running instances is less then the threshold
        then the ECS tasks will be scaled up accordingly.
        """
        # TODO: bring this up when run in aws
        # (running_instances, pending_instances, in_use_instances) = (
        #     self._get_ecs_task_status()
        # )
        global in_use_instances

        q_depths = get_bulk_queues_depths()
        desired_instances = q_depths["total"]
        if desired_instances > self.max_ecs_tasks:
            desired_instances = self.max_ecs_tasks
        if not in_use_instances:
            # TODO: uncomment this for aws
            # self._scale_up_ecs_cluster(desired_instances)
            pass
        if (
            q_depths["total"] >= self.queue_depth_for_scale_up
            and in_use_instances < self.max_ecs_tasks
        ):
            in_use_instances = q_depths["total"]
            # TODO: uncomment this for aws
            # self._scale_up_ecs_cluster(q_depths["total"])
            pass


class TaskScalabilityManager:
    def __init__(
        self,
        celery_app,
    ) -> None:
        self._celery_app: Celery = celery_app
        self.state = self._celery_app.events.State()
        self.scale_mng = WorkerScalability()

    def scale_up(self, event):
        logger.info(f"[NOTIFY][SCALE_UP] t:{get_bulk_queues_depths()["total"]}")
        self.scale_mng.scale_up_workers()

    def scale_down(self, event):
        logger.info(f"[NOTIFY][SCALE_DOWN] t:{get_bulk_queues_depths()["total"]}")
        self.scale_mng.scale_down_workers()

    def run(self):
        events_handler = CeleryEventsManager(
            celery_app=self._celery_app,
            verbose=False,
        )
        events_handler.run(
            handlers={
                # NOTE: the right event is "before_task_publish" or "after_task_publish" but this two events are not working
                # there is an open issue https://github.com/celery/celery/issues/3864
                "task-sent": self.scale_up,
                "task-succeeded": self.scale_down,
                "task-failed": self.scale_down,
            }
        )


class EcsTaskProtection:
    def __init__(self) -> None:
        self.ser = requests.Session()

        retries = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
        )

        self.ser.mount("http://", HTTPAdapter(max_retries=retries))

    def toggle_protection(self, is_protected: bool = True):
        self.ser.put(
            "http://{}/task-protection/v1/state".format(os.getenv("ECS_AGENT_URI", "")),
            headers={
                "Content-Type": "application/json",
            },
            json={
                "ProtectionEnabled": is_protected,
                "ExpiresInMinutes": settings.AWS_TASK_PROTECTION_EXPIRE_IN_MIN,
            },
        )
