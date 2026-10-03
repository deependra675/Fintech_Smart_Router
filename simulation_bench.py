import time 
from typing import Dict
from mock_gateway import MockPaymentGateway
from router_engine import SmartRouter, GatewayStatus
import random
from markov_model import GatewayMarkovModel

def run_traffic_simulation(total_transactions: int = 20):
    # simulates a live production enviornment
    providers = ["razorpay", "cashfree", "stripe"]
    # initializing the smartrouter
    router = SmartRouter(gateways=providers, target_failure_rate=0.02)

    markov = GatewayMarkovModel(p_trip=0.05, p_probe=0.40, p_heal=0.80)
    target_gw = "razorpay"
    previous_state = router.gateways[target_gw].status.value
    gateways: Dict[str, MockPaymentGateway] = {
        "razorpay": MockPaymentGateway("razorpay", baseline_latency_ms=90.0),
        "cashfree": MockPaymentGateway("cashfree", baseline_latency_ms=110.0),
        "stripe": MockPaymentGateway("stripe", baseline_latency_ms=130.0),
    }
    print(f"===Starting Traffic Simulation ({total_transactions} Transaction)===")
    print("Format: [Tx #] Chosen Gateway -> Outcome (Latency) | Health Status\n")

    for tx_num in range(1, total_transactions + 1):
        # we inject failure: crash razorapy at transaction 6
        if tx_num == 6:
            print("\n Chaos: razorpay latency spike (+150ms)\n")
            gateways["razorpay"].latency_spike_ms = 150.0
        if tx_num == 14:
            print("\n Resolution: razorpay latency restored.\n")
            gateways["razorpay"].latency_spike_ms = 0.0

        probe_gw = router.get_probe_target()
        if probe_gw:
            if probe_gw == target_gw:
                markov.record_state_transition(previous_state, "PROBING")
                previous_state = "PROBING"

            probe_result = gateways[probe_gw].charge(amount=10.0, card_token="probe_tok")
            router.record_transaction(
                probe_gw,
                success=probe_result.success,
                latency_ms=probe_result.latency_ms,
                is_probe=True
            )
            p_status = "OK" if probe_result.success else "FAIL"
            print(f"[CANARY PROBE] -> Tested [{probe_gw}] -> {p_status} | Status: {router.gateways[probe_gw].status.value}")

            if probe_gw == target_gw:
                post_probe_state = router.gateways[target_gw].status.value
                markov.record_state_transition(previous_state, post_probe_state)
                previous_state = post_probe_state

        # we ask the router which gateway to send the trasaction to
        selected_gw = router.route()
        client = gateways[selected_gw]

        # execute payment via the chosen provider
        result = client.charge(amount=1000.0, card_token="card_tok_999")

        # reporting the outcome back to the smart router
        router.record_transaction(
            gateway_id=selected_gw,
            success=result.success,
            latency_ms=result.latency_ms
        )

        current_state = router.gateways[target_gw].status.value
        markov.record_state_transition(previous_state, current_state)
        previous_state = current_state

        # status readout
        status_flag = "OK" if result.success else "FAILED"
        current_status = router.gateways[selected_gw].status.value
        s_pos_drift = router.gateways[selected_gw].detector.s_pos
        s_pos_lat = router.gateways[selected_gw].latency_detector.s_pos

        print(
            f"Tx {tx_num:02d}: Routed to [{selected_gw:<8}] -> {status_flag:<6}"
            f"({result.latency_ms:.1f}ms) | Gateway State: {current_status} "
            f"(Fail S+ {s_pos_drift:.2f}, Lat S+: {s_pos_lat:.2f})"
        )
        time.sleep(0.05) # small pacing delay for readability

    print("\n=== Final routing table state ===")
    for gw, metric in router.gateways.items():
        print(
            f"Gateway: {gw:<8} | Status: {metric.status.value:<8} |"
            f"Total: {metric.total_requests:02d} | Failures: {metric.total_failures:02d}"
        )

    print("\n=== Reliability & Markov steady state analysis ===")
    theoretical_pi = markov.solve_stationary_distribution()
    print("Theoretical Stationary Availability:")
    for k, v in theoretical_pi.items():
        print(f" {k:<12}: {v * 100:.2f}%")

    print("\nEmpirical Transition Matrix (State transition counts):")
    print(markov.transition_counts)

if __name__ == "__main__":
    run_traffic_simulation()
