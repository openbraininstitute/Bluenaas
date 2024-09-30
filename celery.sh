#! /bin/sh

echo ${WORKER_NAME}

CMD="celery -A bluenaas.infrastructure.celery worker -n ${WORKER_NAME}@%h -l DEBUG"

echo "Running Celery Worker '${WORKER_NAME}' with reload"

watchmedo auto-restart --directory=./ --pattern=*.py --recursive -- celery -A $CMD --loglevel=DEBUG

# watchmedo auto-restart \
# --patterns="*.py" \
# --ignore-directories \
# --recursive \
# --signal=SIGTERM \
# --kill-after=5 \
# --interval=5 \
# -- $CMD
