from pathlib import Path

from dotenv import load_dotenv
from obp_accounting_sdk import AccountingSessionFactory

# Load environment variables from .env.local
load_dotenv(dotenv_path=Path(".env.local"))
accounting_session_factory = AccountingSessionFactory()
