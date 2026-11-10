import os
import tempfile

# Must be set before backend.app is imported: DB_PATH is resolved at import time.
_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_PATH"] = _DB.name
os.environ["ADMIN_API_TOKEN"] = "test-admin-token"
os.environ["ASK_RATE_LIMIT_PER_MINUTE"] = "0"
os.environ.pop("NIMET_API_KEY", None)
os.environ.pop("NIMET_ENDPOINT", None)
