from bluenaas.infrastructure.redis import redis
from rq import Worker


def start_worker():
    worker = Worker(["low", "medium", "high"], connection=redis)
    worker.work()


if __name__ == "__main__":
    start_worker()
