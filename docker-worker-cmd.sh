#!/bin/bash
set -ex -o pipefail

# Check if QUEUES is set and non-empty
if [ -z "$QUEUES" ]; then
  echo "ERROR: Environment variable QUEUES is not set."
  exit 1
fi

# Check if NUM_WORKERS is set and non-empty
if [ -z "$NUM_WORKERS" ]; then
  echo "ERROR: Environment variable NUM_WORKERS is not set."
  exit 1
fi

# Check if REDIS_URL is set and non-empty
if [ -z "$REDIS_URL" ]; then
  echo "ERROR: Environment variable REDIS_URL is not set."
  exit 1
fi

# Use exec to replace the shell and ensure that SIGINT is sent to the process
# Start the RQ worker pool with specified queues, number of workers, and Redis URL
exec rq worker-pool $QUEUES \
  --url $REDIS_URL \
  --num-workers $NUM_WORKERS
