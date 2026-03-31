import os

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

# Import the app to trigger setup_logging() at module level,
# then remove all loguru sinks so test output stays clean.
import app.app  # noqa: F401, E402
from loguru import logger  # noqa: E402

logger.remove()
