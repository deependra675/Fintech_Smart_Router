# random helps us simulate natural network latency and occasional user errors
import random
# dataclass bundles the payment outcome cleanly
from dataclasses import dataclass
import time


@dataclass
class TransactionResult:
    gateway_id: str
    success: bool
    status_code: int
    latency_ms: float
    error_message: str = ""


class MockPaymentGateway:
    def __init__(self, gateway_id: str, baseline_latency_ms: float = 100.0, baseline_failure_rate: float = 0.02):
        """
        Simulates an external payment gateway provider.
        
        Args:
            gateway_id: Name of provider (e.g., 'razorpay', 'cashfree')
            baseline_latency_ms: Average network round-trip time in milliseconds
        """
        self.gateway_id = gateway_id
        self.baseline_latency_ms = baseline_latency_ms
        
        # Chaos engineering switches: toggle these to simulate upstream outages
        self.force_outage = False
        self.force_timeout = False
        self.latency_spike_ms: float = 0.0

    def charge(self, amount: float, card_token: str) -> TransactionResult:
        """
        Simulates sending an HTTP POST request to the gateway's charge endpoint.
        """
        # 1. Simulate hard network timeout (gateway takes too long to respond)
        if self.force_timeout:
            # Simulate a 3-second delay, then raise a timeout failure
            time.sleep(0.3)  # Shortened for snappy local testing
            return TransactionResult(
                gateway_id=self.gateway_id,
                success=False,
                status_code=504,
                latency_ms=3000.0,
                error_message="Gateway Timeout: Upstream did not respond"
            )

        # 2. Simulate server crash / internal breakdown (HTTP 500)
        if self.force_outage:
            return TransactionResult(
                gateway_id=self.gateway_id,
                success=False,
                status_code=500,
                latency_ms=self.baseline_latency_ms + 25.0,
                error_message="Internal Server Error: Database unreachable"
            )

        # 3. Simulate normal operation:
        # Add a tiny random jitter to latency (e.g., +/- 10ms)
        jitter = random.gauss(0, 10.0)
        actual_latency = max(20.0, self.baseline_latency_ms + jitter + self.latency_spike_ms)

        # Simulate natural user errors (wrong OTP, card decline ~2% of the time)
        # Remember: user errors return success=True to the ROUTER because the gateway itself didn't crash!
        is_user_decline = random.random() < 0.02
        if is_user_decline:
            return TransactionResult(
                gateway_id=self.gateway_id,
                success=True,  # Gateway worked fine, payment simply declined by cardholder bank
                status_code=200,
                latency_ms=actual_latency,
                error_message="DECLINED: Insufficient funds"
            )

        # Nominal success
        return TransactionResult(
            gateway_id=self.gateway_id,
            success=True,
            status_code=200,
            latency_ms=round(actual_latency, 2),
            error_message=""
        )


if __name__ == "__main__":
    print("--- 1. Testing Normal Gateway Response ---")
    mock_razorpay = MockPaymentGateway("razorpay", baseline_latency_ms=100.0)
    res = mock_razorpay.charge(amount=500.0, card_token="tok_visa_123")
    print(f"Status: {res.status_code}, Success: {res.success}, Latency: {res.latency_ms}ms")

    print("\n--- 2. Simulating Sudden Upstream Outage (HTTP 500) ---")
    mock_razorpay.force_outage = True
    res = mock_razorpay.charge(amount=500.0, card_token="tok_visa_123")
    print(f"Status: {res.status_code}, Success: {res.success}, Error: {res.error_message}")

    print("\n--- 3. Simulating Network Timeout (HTTP 504) ---")
    mock_razorpay.force_outage = False
    mock_razorpay.force_timeout = True
    res = mock_razorpay.charge(amount=500.0, card_token="tok_visa_123")
    print(f"Status: {res.status_code}, Success: {res.success}, Latency: {res.latency_ms}ms, Error: {res.error_message}")

    print("\n--- 4. Simulating latency spike (soft degradation) ---")
    mock_razorpay.force_timeout = False
    mock_razorpay.latency_spike_ms = 850.0
    res = mock_razorpay.charge(amount=500.0, card_token="tok_visa_123")
    print(f"Status: {res.status_code}, Success: {res.success}, Latency: {res.latency_ms}ms, Error: '{res.error_message}'")