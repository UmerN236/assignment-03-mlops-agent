"""Create assignment runtime directories and a local Airflow password if absent."""

import json
import os
import secrets
from pathlib import Path

runtime = Path(__file__).resolve().parents[1] / ".local" / "runtime"
airflow = runtime / "airflow"
for directory in (airflow, runtime / "mlflow", airflow / "dags"):
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
passwords = airflow / "simple_auth_manager_passwords.json.generated"
try:
    fd = os.open(passwords, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass  # Preserve the existing credential, just like the user's .env.
else:
    with os.fdopen(fd, "w") as stream:
        json.dump({"admin": secrets.token_urlsafe(32)}, stream)
print("Assignment runtime prepared; credential contents are not displayed.")
