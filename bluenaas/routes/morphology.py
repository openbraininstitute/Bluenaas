import json
import re
from http import HTTPStatus as status
from typing import Dict, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger as L

from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode
from bluenaas.core.model import Model
from bluenaas.domains.morphology import LocationData
from bluenaas.infrastructure.kc.auth import verify_jwt
from bluenaas.utils.bearer_token import token_to_bearer

router = APIRouter(prefix="/morphology")


@router.get("/", response_model=List[Dict[str, LocationData]])
def retrieve_morphology(
    model_id: str = Query(""),
    token: str = Depends(verify_jwt),
):
    try:
        model = Model(
            model_id=model_id,
            token=token_to_bearer(token),
        )

        model.build_model()
        morphology = model.CELL.get_cell_morph()
        morph_str = json.dumps(morphology)
        chunks = re.findall(r".{1,100000}", morph_str)

        def yield_chunks():
            L.info("Sending chunk for morphology...")
            for index, chunk in enumerate(chunks):
                L.debug(f"sending chunk: {index}")
                yield chunk

        return StreamingResponse(
            yield_chunks(),
            media_type="application/x-ndjson",
        )
    except Exception as ex:
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="retrieving morphology data failed",
            details=ex.__str__(),
        ) from ex
