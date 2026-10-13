import pytest
from fastapi.testclient import TestClient
from api import app, router, IDEMPOTENCY_STORE, gateways_client
from router_engine import GatewayStatus

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_router_state():
    IDEMPOTENCY_STORE.clear()
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

def test_charge_success_routes_to_otimal_gateway():
    payload = {"amount": 500.0, "card_token": "tok_visa_4242"}
    response = client.post("/charge", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["gateway_id"] == "cashfree"
    assert data["is_idempotent_replay"] is False

def test_charge_idempotency_replay_prevents_duplicate_charge():
    payload = {"amount": 750.0, "card_token": "tok_visa_4242"}
    headers = {"Idempotency-key": "req_unique_key_001"}

    res1 = client.post("/charge", json=payload, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["is_idempotent_replay"] is False

    res2 = client.post("/charge", json=payload, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["is_idempotent_replay"] is True
    assert data2["transaction_id"] == data1["transaction_id"]
    assert data2["amount"] == data1["amount"]

def test_charge_cascades_to_fallback_on_primary_outage():
    gateways_client["cashfree"].force_outage = True

    try:
        payload = {"amount": 1200.0, "card_token": "tok_visa_4242"}
        response = client.post("/charge", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "SUCCESS"
        assert data["gateway_id"] == "razorpay"

        metric = router.gateways["cashfree"]
        assert metric.total_failures == 1
        assert metric.detector.s_pos > 0.0

        assert router.route() == "razorpay"
    finally:        
        gateways_client["cashfree"].force_outage = False
