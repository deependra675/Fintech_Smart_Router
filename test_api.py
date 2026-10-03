import pytest
from fastapi.testclient import TestClient
from api import app, router

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_router_state():
    for gw in router.gateways.values():
        gw.status = gw.status.HEALTHY
        gw.detector.s_pos = 0.0
        gw.latency_detector.s_pos = 0.0
        gw.consecutive_probe_successes = 0

def test_get_optimal_route_healthy():
    response = client.post("/route")
    assert response.status_code == 200
    data = response.json()
    assert data["selected_gateway"] == "cashfree"
    assert data["gateway_status"] == "HEALTHY"
    assert "composite_cost" in data

def test_feedback_anomaly_trips_failover():
    # inject 3 sequential high latency transactions on cashfree
    for _ in range(3):
        res = client.post("/feedback", json={
            "gateway_id": "cashfree",
            "success": True,
            "latency_ms": 350.0,
            "is_probe": False
        })
        assert res.status_code == 200

    # verify cashfee is marked degraded
    assert res.json()["status"] == "DEGRADED"

    # route request must now fail over to razorpay
    route_res = client.post("/route")
    assert route_res.status_code == 200
    assert route_res.json()["selected_gateway"] == "razorpay"

def test_matrics_endpoint_reports_markov_availability():
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "gateway_health" in data
    assert "markov_steady_state_availability" in data
    assert "pi_healthy" in data["markov_steady_state_availability"]