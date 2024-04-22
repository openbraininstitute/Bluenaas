"""Main."""
import json
import os
import re
import sched
import signal
from contextlib import asynccontextmanager
from threading import Thread

import boto3
import fastapi
from botocore.exceptions import ClientError
from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.responses import Response

from .handler import divide_sim_chunks, message_handler
from .settings import L

SHUTDOWN_TIMER = 600  # sec
SCHEDULER = sched.scheduler()


def _shutdown_timer():
    if len(SCHEDULER.queue) == 0:
        L.info("Server idle timeout, shutting down...")
        os.kill(os.getpid(), signal.SIGTERM)


def no_cache(response: Response) -> Response:
    """Add Cache-Control: no-cache to the response headers."""
    response.headers["Cache-Control"] = "no-cache"
    return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start idle shutdown timer and close websockt connection when done."""
    SCHEDULER.enter(SHUTDOWN_TIMER, 1, _shutdown_timer)
    Thread(target=SCHEDULER.run, daemon=True).start()
    yield
    apigw = os.getenv("APIGW_ENDPOINT")
    region = os.getenv("APIGW_REGION")
    conn = os.getenv("APIGW_CONN_ID")
    apigw = boto3.client("apigatewaymanagementapi", endpoint_url=apigw, region_name=region)
    try:
        apigw.delete_connection(ConnectionId=conn)
    except ClientError:
        L.exception("Couldn't post to connection")
    except apigw.exceptions.GoneException:
        L.exception("Connection is gone.")


APP = FastAPI(lifespan=lifespan)


def send_message(apigw, conn, data):
    """Send message to frontend."""
    try:
        apigw.post_to_connection(Data=json.dumps(data),
                                 ConnectionId=conn)
    except ClientError:
        L.exception("Couldn't post to connection")
    except apigw.exceptions.GoneException:
        L.exception("Connection is gone.")


def process_message(msg: dict):
    """Call different functions based on message."""
    apigw = os.environ["APIGW_ENDPOINT"]
    region = os.environ["APIGW_REGION"]
    conn = os.environ["APIGW_CONN_ID"]
    L.info("apigw=%s region=%s conn=%s", apigw, region, conn)
    L.info("processing msg=%s ...", msg)

    try:
        result = message_handler(msg)
    except Exception as e:
        L.exception("Error during processing msg=%s: %s", msg, e)
        raise Exception(e) from e

    apigw = boto3.client("apigatewaymanagementapi", endpoint_url=apigw, region_name=region)

    if result['cmd'] == 'start_simulation_done':
        partial_data_cmd = 'partial_simulation_data'

        for recording in result['data']:
            L.info('Sending chunk for recording %s ...', recording['name'])
            chunks = divide_sim_chunks(partial_data_cmd,
                                       recording['name'],
                                       recording['v'],
                                       recording['t'])
            for index, chunk in enumerate(chunks):
                L.debug("sending chunk: %s", index)
                send_message(apigw, conn, chunk)

        L.info("all chunks were sent")
        send_message(apigw, conn, {'cmd': result['cmd'], 'data': True})

    elif result['cmd'] == 'get_ui_data_done':
        partial_morph_cmd = 'partial_morphology_data'

        # TODO: improve this
        # strinfigy and divide in chunks the object
        morph_str = json.dumps(result['data']['morphology'])
        chunks = re.findall(r'.{1,100000}', morph_str)

        L.info('Sending chunk for morphology...')
        for index, chunk in enumerate(chunks):
            L.debug("sending chunk: %s", index)
            data = {
                'cmd': partial_morph_cmd,
                'data': chunk,
            }
            send_message(apigw, conn, data)

        L.info("all chunks were sent")
        send_message(apigw, conn, {'cmd': result['cmd'], 'data': True})
    else:
        send_message(apigw, conn, result)


@APP.post("/default")
def default(msg: dict, background_tasks: BackgroundTasks):
    """Process message."""
    L.info("SVC DEFAULT msg=%s", msg)
    # reset idle shutdown timer
    SCHEDULER.enter(SHUTDOWN_TIMER, 1, _shutdown_timer)
    background_tasks.add_task(process_message, msg)
    return JSONResponse(status_code=202, content={"message": "Processing message"})


@APP.post("/shutdown")
def shutdown():
    """Shutdown the service."""
    L.info("shutdown")
    os.kill(os.getpid(), signal.SIGTERM)
    return fastapi.Response(status_code=202)


@APP.get("/health", dependencies=[Depends(no_cache)])
async def health():
    """Health endpoint."""
    L.info("health")
    return fastapi.Response(status_code=204)
