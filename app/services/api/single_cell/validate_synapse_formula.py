from loguru import logger
import sympy as sp
from http import HTTPStatus as status
from app.core.exceptions import BlueNaasError, BlueNaasErrorCode  # type: ignore


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
