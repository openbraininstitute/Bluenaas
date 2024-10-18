#! /bin/sh

ENV=${ENV:-development}  # Default is 'development' if ENV is not set
CELERY_APP="bluenaas.infrastructure.celery"

echo ${WORKER_NAME}

if [ "$ENV" = "production" ]; then
    CMD="celery -A ${CELERY_APP} worker -n ${WORKER_NAME}@%h -l WARNING -E"
    echo "Running Celery Worker '${WORKER_NAME}' in production mode"
    exec $CMD
else
    echo "Running Celery Worker '${WORKER_NAME}' in development mode with auto-restart"
    watchmedo auto-restart --directory=./ --pattern=*.py --recursive -- \
        celery -A ${CELERY_APP} worker -n ${WORKER_NAME}@%h -l WARNING -E
fi