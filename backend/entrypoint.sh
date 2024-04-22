#!/bin/sh
timeout 1200 uvicorn blue_naas.main:APP --host 0.0.0.0 --port 8080 --proxy-headers --log-config logging.yaml
