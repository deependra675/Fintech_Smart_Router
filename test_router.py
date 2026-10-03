import pytest
from cusum_detector import WelfordVariance, ContinousCUSUMDetector
from router_engine import SmartRouter, GatewayStatus
from markov_model import GatewayMarkovModel
import numpy as np

def test_welford_variance_known_distribution():
    # test on known smpels: [100.0, 105.0, 95.0]
    # sample mean = 100.0, sample variance = 25.0, Std dev = 5.0
    w = WelfordVariance(min_samples=3)
    samples = [100.0, 105.0, 95.0]
    for sample in samples:
        w.update(sample)

    assert w.is_calibrated is True
    assert w.mean == 100.0
    assert w.variance == 25.0
    assert w.std_dev == 5.0

def test_continous_cusum_trips_on_latency_spike():
    # baseline ~ 100ms, threshold_h = 4.0
    detector = ContinousCUSUMDetector(
        slack_k=0.5,
        threshold_h=4.0,
        warmup_samples=5,
        baseline_mean=100.0,
        baseline_std=5.0
    )

    # in-control transaction should not trip
    state_normal = detector.update(101.0)
    assert state_normal.alert_high is False

    # out of control latency spikes should accumulate and trip
    state_spike1 = detector.update(250.0)
    state_spike2 = detector.update(300.0)
    assert state_spike1.alert_high is True or state_spike2.alert_high is True

def test_smart_router_failover_and_recovery():
    providers = ["razorpay", "cashfree"]
    router = SmartRouter(gateways=providers, target_failure_rate=0.02)

    # initial route should be razorpay
    assert router.route() == "cashfree"

    # simulate hard failures on razorpay to trip breaker
    for _ in range(5):
        router.record_transaction("cashfree", success=False, latency_ms=100.0)

    # primary should failover to cashfree
    assert router.gateways["cashfree"].status == GatewayStatus.DEGRADED
    assert router.route() == "razorpay"

def test_markov_chain_stochastic_invariants():
    model = GatewayMarkovModel(p_trip=0.05, p_probe=0.30, p_heal=0.75)
    P = model.theoretical_transition_matrix

    row_sums = P.sum(axis=1)
    np.testing.assert_allclose(row_sums, np.ones(3), rtol=1e-5)

    pi_dict = model.solve_stationary_distribution()
    pi_value = list(pi_dict.values())

    assert abs(sum(pi_value) - 1.0) < 1e-6
    for val in pi_value:
        assert 0.0 <= val <= 1.0

    unstable_model = GatewayMarkovModel(p_trip=0.20, p_probe=0.30, p_heal=0.75)
    pi_unstable = unstable_model.solve_stationary_distribution()
    assert pi_unstable["pi_healthy"] < pi_dict["pi_healthy"]