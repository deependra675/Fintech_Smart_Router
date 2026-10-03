from typing import Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from markov_model import GatewayMarkovModel
from router_engine import GatewayStatus, SmartRouter

app = FastAPI(
    title="Smart Payment Router API",
    version="1.0.0",
    description="Intelligent payment gateway routing using CUSUM anomaly detection and Markov availability."
)

# start router with the 3 gateways and markov model
PROVIDERS = ["cashfree", "razorpay", "strip"]
router = SmartRouter(gateways=PROVIDERS, target_failure_rate=0.02)
markov = GatewayMarkovModel(p_trip=0.05, p_probe=0.40, p_heal=0.80)

# Data Shapes - pydantic models - for making sure incoming and outgoing data have exact right structure.
class RouteResponse(BaseModel):
    selected_gateway: str
    gateway_status: str
    composite_cost: float

class FeedbackRequest(BaseModel):
    gateway_id: str = Field(..., example="razorpay")
    success: bool = Field(..., example=True)
    latency_ms: float = Field(..., example=85.4)
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
    cost = router.compute_gateay_cost(selected)
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
    