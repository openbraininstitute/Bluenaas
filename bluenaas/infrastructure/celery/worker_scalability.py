import time
from loguru import logger
from bluenaas.config.settings import settings
from bluenaas.infrastructure.celery.aws import (
    get_cloudwatch_boto_client,
    get_ecs_boto_client,
)
from bluenaas.infrastructure.celery.events_manager import CeleryEventsManager
from bluenaas.infrastructure.celery.broker_manager import get_bulk_queues_depths

# NOTE: this global variables are just for debugging
scale_up_count = 0
scale_down_count = 0
total_worker = 0
in_use_instances = 2


class WorkerScalability:
    # NOTE: this should be env variables
    # Number of tasks in queues to scale up workers.
    queue_depth_for_scale_up = 4
    # Number of tasks in queues to scale down workers.
    queue_depth_for_scale_down = 2
    # Minimum support workers ECS can launch
    min_ecs_tasks = 2
    # Maximum support workers ECS can launch
    max_ecs_tasks = 10

    def _get_ecs_task_status(self):
        client = get_ecs_boto_client()
        service_type = client.describe_services(
            cluster=settings.CLUSTER_NAME,
            services=[
                settings.SERVICE_NAME,
            ],
        )["services"][0]
        running_instances = service_type["runningCount"]
        pending_instances = service_type["pendingCount"]

        return (running_instances, pending_instances)

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
                cluster=settings.CLUSTER_NAME,
                services=[
                    settings.SERVICE_NAME,
                ],
            )
            if (
                service_type["services"]
                and service_type["services"][0]["desiredCount"] != desired_count
            ):
                client.update_service(
                    cluster=settings.CLUSTER_NAME,
                    service=settings.SERVICE_NAME,
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
        (running_instances, pending_instances) = self._get_ecs_task_status()
        in_use_instances = running_instances + pending_instances
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
        # TODO: bring this up when run in aws
        # (running_instances, pending_instances) = self._get_ecs_task_status()
        # in_use_instances = running_instances + pending_instances
        q_depths = get_bulk_queues_depths()
        global scale_down_count, in_use_instances
        logger.info(
            f"[APPLY][SCALE_DOWN][TOTAL][1] {in_use_instances=} total:{q_depths["total"]}"
        )
        if in_use_instances > q_depths["total"] and (
            in_use_instances > self.min_ecs_tasks
        ):
            logger.info(
                f'[APPLY][SCALE_DOWN] t:{q_depths["total"]}/l:{self.queue_depth_for_scale_down}'
            )

            scale_down_count += 1
            in_use_instances = q_depths["total"]
            logger.info(
                f"[APPLY][SCALE_DOWN][TOTAL][2] {scale_down_count=} total:{q_depths["total"]}"
            )
            # TODO: uncomment this for aws
            # self._update_ecs_task(q_depths["total"])
        if (
            q_depths["total"] == 0
            or q_depths["total"] <= self.queue_depth_for_scale_down
        ) and (in_use_instances > self.min_ecs_tasks):
            logger.info(
                f'[APPLY][SCALE_DOWN] t:{q_depths["total"]}/l:{self.queue_depth_for_scale_down}'
            )

            scale_down_count += 1
            in_use_instances = self.min_ecs_tasks
            logger.info(
                f"[APPLY][SCALE_DOWN][TOTAL][2] {in_use_instances=} total:{q_depths["total"]}"
            )
            # TODO: uncomment this for aws
            # self._update_ecs_task(self.min_ecs_tasks)

    def scale_up_workers(self):
        """
        Scale up ECS tasks if the queue depth exceeds the threshold.

        If the queue depth exceeds `queue_depth_for_scale_up`, and running instances is less then the threshold
        then the ECS tasks will be scaled up accordingly.
        """
        # TODO: bring this up when run in aws
        # (running_instances, pending_instances) = self._get_ecs_task_status()
        # in_use_instances = running_instances + pending_instances
        q_depths = get_bulk_queues_depths()
        global scale_up_count, in_use_instances
        logger.info(
            f"[APPLY][SCALE_UP][TOTAL][1] total:{q_depths["total"]} {in_use_instances=}"
        )
        if (
            q_depths["total"] >= self.queue_depth_for_scale_up
            and in_use_instances < self.max_ecs_tasks
        ):
            logger.info(
                f'[APPLY][SCALE_UP] t:{q_depths["total"]}/l:{self.queue_depth_for_scale_up}'
            )

            scale_up_count += 1
            in_use_instances = q_depths["total"]
            logger.info(
                f"[APPLY][SCALE_UP][TOTAL][2] total:{q_depths["total"]} {in_use_instances=}"
            )
            # TODO: uncomment this for aws
            # self._scale_up_ecs_cluster(q_depths["total"])


class ScalabilityManager:
    def __init__(
        self,
        celery_app,
    ) -> None:
        self._celery_app = celery_app
        self.state = self._celery_app.events.State()
        self.scale_mng = WorkerScalability()

    def scale_up(self, event):
        logger.info(f"[NOTIFY][SCALE_UP] t:{get_bulk_queues_depths()["total"]}")
        self.scale_mng.scale_up_workers()

    def scale_down(self, event):
        logger.info(f"[NOTIFY][SCALE_DOWN] t:{get_bulk_queues_depths()["total"]}")
        self.scale_mng.scale_down_workers()

    def run(self):
        self.events_handler = CeleryEventsManager(
            celery_app=self._celery_app,
            verbose=False,
        )
        self.events_handler.run(
            handlers={
                # NOTE: the right event is "before_task_publish" or "after_task_publish" but this two events are not working
                # there is an open issue https://github.com/celery/celery/issues/3864
                "task-sent": self.scale_up,
                "task-received": self.scale_down,
            }
        )
