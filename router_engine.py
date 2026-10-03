from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Dict, List, Optional

from cusum_detector import CUSUMDetector, ContinousCUSUMDetector


class GatewayStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


@dataclass
class GatewayMetric:
    gateway_id: str
    detector: CUSUMDetector
    latency_detector: ContinousCUSUMDetector
    status: GatewayStatus = GatewayStatus.HEALTHY
    mdr: float = 0.018
    total_requests: int = 0
    total_failures: int = 0
    consecutive_probe_successes: int = 0
    last_updated: float = field(default_factory=time.time)
    last_probed: float = 0.0


class SmartRouter:
    def __init__(
        self,
        gateways: List[str],
        target_failure_rate: float = 0.02,
        probe_interval_seconds: float = 0.1,
        required_success_streak: int = 2
    ):
        self.gateways: Dict[str, GatewayMetric] = {}
        self.priority_order: List[str] = gateways
        self.probe_interval = probe_interval_seconds
        self.required_streak = required_success_streak

        fees = {
            "cashfree": 0.015,
            "razorpay": 0.018,
            "stripe": 0.020
        }
        
        for gw in gateways:
            self.gateways[gw] = GatewayMetric(
                gateway_id=gw,
                mdr=fees.get(gw.lower(), 0.018),
                detector=CUSUMDetector(
                    target_mean=target_failure_rate,
                    slack=0.03,
                    threshold_h=1.00
                ),
                latency_detector=ContinousCUSUMDetector(
                    baseline_mean=100.0,
                 baseline_std=15.0,
                    slack_k=0.5,
                    threshold_h=4.0
                )
            )

    def get_probe_target(self) -> Optional[str]:
        """Checks if a degraded gateway is eligible for a lightweight test probe."""
        now = time.time()

        for gw in self.priority_order:
            metric = self.gateways[gw]

            if metric.status == GatewayStatus.DEGRADED:
                if (now - metric.last_probed) >= self.probe_interval:
                    metric.last_probed = now
                    return gw

        return None

    def compute_gateay_cost(
            self,
            gateway_id: str,
            w_fee: float = 0.4,
            w_lat: float = 0.3,
            w_risk: float = 0.3
    ) -> float:
        metric = self.gateways[gateway_id]
        if metric.status == GatewayStatus.DEGRADED:
            return float("inf")
        cost_fee = metric.mdr * 50.0

        mean_lat = (
            metric.latency_detector.welford.mean
            if metric.latency_detector.welford.is_calibrated
            else 100.0
        )
        cost_lat = mean_lat / 100.0

        cost_risk = metric.detector.s_pos + metric.latency_detector.s_pos
        return (w_fee * cost_fee) + (w_lat * cost_lat) + (w_risk * cost_risk)

    def route(self) -> str:
        """Pick the highest-priority healthy gateway."""
        healthy_gws = [
            gw for gw in self.priority_order
            if self.gateways[gw].status == GatewayStatus.HEALTHY
        ]
        if healthy_gws:
            return min(healthy_gws, key=lambda gw: self.compute_gateay_cost(gw))
        
        return min(
            self.gateways.keys(),
            key=lambda gw: self.gateways[gw].detector.s_pos
        )

    def get_route(self) -> str:
        return self.route()

    def record_transaction(
        self,
        gateway_id: str,
        success: bool,
        latency_ms: float = 0.0,
        is_probe: bool = False
    ) -> None:
        """Ingest transaction or probe result and update gateway health."""

        if gateway_id not in self.gateways:
            raise KeyError(f"Unknown gateway: {gateway_id}")

        metric = self.gateways[gateway_id]

        metric.total_requests += 1
        metric.last_updated = time.time()

        observation = 0.0 if success else 1.0

        if not success:
            metric.total_failures += 1
            metric.consecutive_probe_successes = 0

        # 1. update binary failure CUSUM
        state_bin = metric.detector.update(observation)

        # 2. Update continous latency CUSUM
        state_lat = metric.latency_detector.update(latency_ms)

        # 3. Trip circuit breaker on hard failures OK latency anomallies
        if not is_probe:
            if state_bin.alert_high or state_lat.alert_high:
                if metric.status != GatewayStatus.DEGRADED:
                    reason = "binary failure" if state_bin.alert_high else "latency drift"
                    print(f"\n[ALERT] Tripping {gateway_id} to DEGRADED due to {reason}!")
                metric.status = GatewayStatus.DEGRADED

        # 4. handle canary auto healing
        if metric.status == GatewayStatus.DEGRADED and is_probe and success:
            metric.consecutive_probe_successes += 1

            print(
                f"[RECOVERY] {gateway_id}: "
                f"{metric.consecutive_probe_successes}/{self.required_streak}"
            )

            if metric.consecutive_probe_successes >= self.required_streak:
                metric.status = GatewayStatus.HEALTHY
                metric.detector.reset()
                metric.latency_detector.reset()
                metric.consecutive_probe_successes = 0

                print(
                    f"[RECOVERY] {gateway_id} restored to HEALTHY"
                )


if __name__ == "__main__":
    providers = ["razorpay", "cashfree", "stripe"]

    router = SmartRouter(
        gateways=providers,
        required_success_streak=2
    )

    print("Initial primary route:", router.route())

    print("\n--- Test 1: Two failures trip Razorpay to DEGRADED ---")

    router.record_transaction(
        "razorpay",
        success=False
    )

    router.record_transaction(
        "razorpay",
        success=False
    )

    print(
        "Razorpay status:",
        router.gateways["razorpay"].status.value
    )

    print(
        "Active route shifted to:",
        router.route()
    )

    print("\n--- Two consecutive successful probes auto heal Razorpay ---")

    router.record_transaction(
        "razorpay",
        success=True,
        is_probe=True
    )

    print(
        "Probe 1 success -> Razorpay status:",
        router.gateways["razorpay"].status.value
    )

    router.record_transaction(
        "razorpay",
        success=True,
        is_probe=True
    )

    print(
        "Probe 2 success -> Razorpay status:",
        router.gateways["razorpay"].status.value
    )

    print(
        "Active route restored to:",
        router.route()
    )
    print("\n--- Test 3: Soft failure (latency spike with 100% HTTP 200 OK) ---")
    router.record_transaction("razorpay", success=True, latency_ms=210.0)
    router.record_transaction("razorpay", success=True, latency_ms=220.0)
    router.record_transaction("razorpay", success=True, latency_ms=230.0)

    print("Razorpay status after latency spike:", router.gateways["razorpay"].status.value)
    print("Active route shifted to:", router.route())                                                                           