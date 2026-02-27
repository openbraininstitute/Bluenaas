from http import HTTPStatus

from loguru import logger
from obp_accounting_sdk import OneshotSession, AsyncOneshotSession
from obp_accounting_sdk._async.oneshot import AsyncNullOneshotSession
from obp_accounting_sdk._sync.oneshot import NullOneshotSession
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError

from app.core.exceptions import AppError, AppErrorCode


async def make_accounting_reservation_async(
    accounting_session: AsyncOneshotSession | AsyncNullOneshotSession,
) -> None:
    """Make an async accounting reservation with error handling."""
    try:
        await accounting_session.make_reservation()
        logger.info("Accounting reservation success")
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the task",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex


def make_accounting_reservation_sync(
    accounting_session: OneshotSession | NullOneshotSession,
) -> None:
    """Make a sync accounting reservation with error handling."""
    try:
        accounting_session.make_reservation()
        logger.info("Accounting reservation success")
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the task",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex
