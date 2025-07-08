from http import HTTPStatus as status
from uuid import UUID

import sympy as sp
from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from rq import Queue

from app.core.exceptions import BlueNaasError, BlueNaasErrorCode
from app.domains.morphology import (
    SynapsePlacementBody,
)
from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def generate_synapses(
    model_id: UUID,
    params: SynapsePlacementBody,
    *,
    request: Request,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext,
) -> StreamingResponse:
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = await dispatch(
        job_queue,
        JobFn.GENERATE_SYNAPSES,
        job_args=(
            model_id,
            params,
        ),
        job_kwargs={"access_token": access_token, "project_context": project_context},
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")


def validate_synapse_generation_formula(formula: str):
    try:
        expr = sp.sympify(formula)
        allowed_symbols = {sp.Symbol("x"), sp.Symbol("X")}
        symbols = expr.free_symbols

        if symbols.issubset(allowed_symbols):
            return True
        else:
            return False

    except (sp.SympifyError, SyntaxError) as ex:
        logger.error(
            f"validating synapse generation formula failed [SympifyError, SyntaxError] {ex}"
        )
        return False

    except Exception as ex:
        logger.error(f"validating synapse generation formula failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="validating synapse generation formula failed",
            details=ex.__str__(),
        ) from ex
