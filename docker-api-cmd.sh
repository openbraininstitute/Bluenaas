#!/bin/bash
set -ex -o pipefail

# Use exec to replace the shell and ensure that SIGINT is sent to the process
exec uvicorn app.app:app --port 8000 --host 0.0.0.0
