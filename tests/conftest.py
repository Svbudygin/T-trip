import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("TEST_API_TIMEOUT", "60"))


@pytest.fixture(scope="session")
def api_available():
    try:
        with httpx.Client(base_url=API_URL, timeout=5.0) as client:
            client.post(
                "/search",
                json={
                    "from_lat": 55.7558,
                    "from_lon": 37.6173,
                    "to_lat": 59.9343,
                    "to_lon": 30.3351,
                    "optimize_by": "time",
                },
            )
    except httpx.HTTPError as exc:
        pytest.skip(f"API unavailable at {API_URL}: {exc}")
    return True


@pytest.fixture
def api_client(api_available):
    with httpx.Client(base_url=API_URL, timeout=TIMEOUT) as client:
        yield client
