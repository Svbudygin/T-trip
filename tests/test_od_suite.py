import pytest

from od_loader import build_payload, load_od_cases
from validators import assert_expectations, assert_response_invariants

CASES = load_od_cases()

assert len(CASES) == 50, f"expected 50 OD cases, got {len(CASES)}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_od_case(case, api_client):
    payload = build_payload(case)
    expect = case.get("expect", {})
    expected_status = expect.get("status", 200)

    response = api_client.post("/search", json=payload)
    assert response.status_code == expected_status, response.text

    if expected_status != 200:
        return

    data = response.json()
    min_routes = expect.get("min_routes", 1)
    if min_routes > 0:
        assert_response_invariants(data)
    assert_expectations(data, expect)
