from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from markov_model import GatewayMarkovModel
from router_engine import GatewayStatus, SmartRouter
from mock_gateway import MockPaymentGateway

app = FastAPI(
    title="Smart Payment Router API",
    version="1.0.0",
    description="Intelligent payment gateway routing using CUSUM anomaly detection and Markov availability."
)

# start router with the 3 gateways and markov model
PROVIDERS = ["cashfree", "razorpay", "stripe"]
router = SmartRouter(gateways=PROVIDERS, target_failure_rate=0.02)
markov = GatewayMarkovModel(p_trip=0.05, p_probe=0.40, p_heal=0.80)

# active mock gateway instances
gateways_client: Dict[str, MockPaymentGateway] = {
    "cashfree": MockPaymentGateway("cashfree", baseline_latency_ms=110.0),
    "razorpay": MockPaymentGateway("razorpay", baseline_latency_ms=90.0),
    "stripe": MockPaymentGateway("stripe", baseline_latency_ms=130.0),
}
IDEMPOTENCY_STORE: Dict[str, dict] = {}

# Data Shapes - pydantic models - for making sure incoming and outgoing data have exact right structure.
class RouteResponse(BaseModel):
    selected_gateway: str
    gateway_status: str
    composite_cost: float

class ChargeRequest(BaseModel):
    amount: float = Field(..., gt=0, json_schema_extra={"example":1000.0})
    card_token: str = Field(..., json_schema_extra={"example": "tok_visa_4242"})

class ChargeResponse(BaseModel):
    transaction_id: str
    gateway_id: str
    status: str
    amount: float
    latency_ms: float
    is_idempotent_replay: bool = False

class FeedbackRequest(BaseModel):
    gateway_id: str = Field(..., json_schema_extra={"example": "razorpay"})
    success: bool = Field(..., json_schema_extra={"example": True})
    latency_ms: float = Field(..., json_schema_extra={"example": 85.4})
    is_probe: bool = Field(default=False)

class FeedbackResponse(BaseModel):
    gateway_id: str
    status: str
    s_pos_failure: float
    s_pos_latency: float
    message: str

# Endpoint 1
@app.post("/route", response_model=RouteResponse)
def get_optimal_route():
    selected = router.route()
    cost = router.compute_gateway_cost(selected)
    status = router.gateways[selected].status.value

    return RouteResponse(
        selected_gateway=selected,
        gateway_status=status,
        composite_cost=round(cost, 4)
    )

# Endpoint 2
@app.post("/feedback", response_model=FeedbackResponse)
def record_transaction_feedback(feedback: FeedbackRequest):
    if feedback.gateway_id not in router.gateways:
        raise HTTPException(
            status_code=404,
            detail=f"Gateway '{feedback.gateway_id}', is not in the router."
        )

    # ingest telemetry into the engine
    router.record_transaction(
        gateway_id=feedback.gateway_id,
        success=feedback.success,
        latency_ms=feedback.latency_ms,
        is_probe=feedback.is_probe
    )

    metric = router.gateways[feedback.gateway_id]
    return FeedbackResponse(
        gateway_id=feedback.gateway_id,
        status=metric.status.value,
        s_pos_failure=round(metric.detector.s_pos, 4),
        s_pos_latency=round(metric.latency_detector.s_pos, 4),
        message="Telemetry recorded and CUSUM updated."
    )

# Endpoint 3
@app.post("/charge", response_model=ChargeResponse)
def execute_charge(
    charge: ChargeRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    if idempotency_key and idempotency_key in IDEMPOTENCY_STORE:
        cached = IDEMPOTENCY_STORE[idempotency_key].copy()
        cached["is_idempotent_replay"] = True
        return cached

    chosen_gw = router.route()
    client = gateways_client[chosen_gw]

    res = client.charge(amount=charge.amount, card_token=charge.card_token)

    router.record_transaction(
        gateway_id=chosen_gw,
        success=res.success,
        latency_ms=res.latency_ms
    )

    if not res.success and res.status_code >= 500:
        fallback_gw = router.route()
        if fallback_gw != chosen_gw:
            fallback_client = gateways_client[fallback_gw]
            res = fallback_client.charge(amount=charge.amount, card_token=charge.card_token)
            router.record_transaction(
                gateway_id=fallback_gw,
                success=res.success,
                latency_ms=res.latency_ms
            )
            chosen_gw = fallback_gw

    response_payload = {
        "transaction_id": f"txn_{idempotency_key or 'anon'}",
        "gateway_id": chosen_gw,
        "status": "SUCCESS" if res.success else "FAILED",
        "amount": charge.amount,
        "latency_ms": res.latency_ms,
        "is_idempotent_replay": False
    }

    if idempotency_key:
        IDEMPOTENCY_STORE[idempotency_key] = response_payload

    return response_payload

@app.get("/metrics")
def get_system_metrics():
    stats = {}
    for name, metric in router.gateways.items():
        stats[name] = {
            "status": metric.status.value,
            "mdr_fee": metric.mdr,
            "total_requests": metric.total_requests,
            "total_failures": metric.total_failures,
            "failure_drift_score": round(metric.detector.s_pos, 4),
            "latency_drift_score": round(metric.latency_detector.s_pos, 4)
        }

    # pi * P = pi
    pi = markov.solve_stationary_distribution()

    return{
        "gateway_health": stats,
        "markov_steady_state_availability": {k: f"{v * 100:.2f}%" for k, v in pi.items()}
    }
    