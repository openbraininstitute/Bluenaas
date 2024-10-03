import time
from threading import Thread

from loguru import logger


# NOTE: This is just for testing purposes
class MonitorThread(object):
    def __init__(self, celery_app, interval=4):
        self.celery_app = celery_app
        self.interval = interval

        self.state = self.celery_app.events.State()

        self.thread = Thread(target=self.run, args=())
        self.thread.daemon = True
        self.thread.start()

    def catchEvent(self, event):
        if event["type"] != "worker-heartbeat":
            logger.info(event)
            self.state.event(event)

    def run(self):
        while True:
            try:
                with self.celery_app.connection() as connection:
                    recv = self.celery_app.events.Receiver(
                        connection, handlers={"*": self.catchEvent}
                    )
                    recv.capture(limit=None, timeout=None, wakeup=True)

            except (KeyboardInterrupt, SystemExit):
                raise

            except Exception:
                pass

            time.sleep(self.interval)


def main():
    from bluenaas.infrastructure.celery import celery_app
    from bluenaas.infrastructure.celery.monitor import MonitorThread

    MonitorThread(celery_app=celery_app, interval=1).run()
