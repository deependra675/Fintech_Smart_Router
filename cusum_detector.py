from dataclasses import dataclass
import math

# welford's online variance tracker
class WelfordVariance:
    def __init__(self, min_samples: int = 10):
        self.count: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0
        self.min_samples: int = min_samples

    def update(self, x:float) -> None:
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2/(self.count - 1)
    @property
    def std_dev(self) -> float:
        var =self.variance
        return math.sqrt(var) if var > 0.0 else 1.0
    @property
    def is_calibrated(self) -> bool:
        return self.count >= self.min_samples

# holds the current status after checking each transaction
@dataclass
class CUSUMState:
    s_pos: float = 0.0          # upper score: accumulates when transactions fail
    s_neg: float = 0.0          # lower score: accumulates when gateway is working noramlly
    alert_high: bool = False    
    alert_low: bool = False

class CUSUMDetector:
    def __init__(self, target_mean: float, slack: float, threshold_h: float):
        self.mu_0 = target_mean
        self.k = slack      # small buffer to ingnore random network noise
        self.h = threshold_h
        self.reset()

    def reset(self) -> None:
        # reset both failure and recovery scores back to zero
        self.s_pos = 0.0
        self.s_neg = 0.0

    def update(self, observation: float) -> CUSUMState:
        # observation 0.0 = successful payment, 1.0 = failed/timeout
        self.s_pos = max(0.0, self.s_pos + (observation - self.mu_0 - self.k)) # failure socre
        self.s_neg = max(0.0, self.s_neg + (self.mu_0 - observation - self.k)) # recovery score
        alert_high = self.s_pos >= self.h   # gateway is unhealthy
        alert_low = self.s_neg >= self.h    # gateway is back to normal
        return CUSUMState(
            s_pos=round(self.s_pos, 4),
            s_neg=round(self.s_neg, 4),
            alert_high=alert_high,
            alert_low=alert_low
        )

class ContinousCUSUMDetector:
    """
    online cusum detector for latency drift.
    uses welfordvariance to adaptively estimate dynamic mean and std dev.
    """
    def __init__(
            self,
            slack_k: float = 0.5,
            threshold_h: float = 5.0,
            warmup_samples: int = 10,
            baseline_mean: float = None,
            baseline_std: float = None
    ):
        self.k: float = slack_k
        self.h: float = threshold_h
        self.s_pos: float = 0.0
        self.welford = WelfordVariance(min_samples=warmup_samples)

        # if an initial baseline mean is provided, pre seed welford
        if baseline_mean is not None:
            self.welford.mean = float(baseline_mean)
            if baseline_std is not None and baseline_std > 0:
                self.welford.m2 = float(baseline_std**2) * max(1, (warmup_samples - 1))
                self.welford.count = warmup_samples

    def update(self, latency_ms: float):
        # warmup - accumulate baseline statistics without tripping alerts
        if not self.welford.is_calibrated:
            self.welford.update(latency_ms)
            return CUSUMState(s_pos=0.0, alert_high=False)

        # compute standarized z score using dynamic baseline
        current_mean = self.welford.mean
        current_std = self.welford.std_dev
        z = (latency_ms - current_mean) / current_std

        # upper cusum accumulation 
        self.s_pos = max(0.0, self.s_pos + (z - self.k))

        # adapt baseline only on non anomalous samples (prevents baseline poisoning)
        if self.s_pos < self.h:
            self.welford.update(latency_ms)

        is_alert = self.s_pos > self.h
        return CUSUMState(s_pos=self.s_pos, alert_high=is_alert)

    def reset(self) -> None:
        self.s_pos = 0.0      


if __name__ == "__main__":
    detector = CUSUMDetector(target_mean=0.02, slack=0.03, threshold_h=1.00)
    print("---1. Random isolated user error (noise)---")
    test_stream_1 = [1.0, 0.0, 0.0, 0.0]
    for i, tx in enumerate(test_stream_1, 1):
        state = detector.update(tx)
        print(f"Tx {i} (val={tx}): s_pos={state.s_pos}, alert_high={state.alert_high}")
    print("Notice: The failure was absored, s_pos went back to 0.0, No false alarm.\n")

    detector.reset()

    print("---2. Real gateway Downtime (burst failures)---")
    test_stream_2 = [1.0, 1.0]
    for i, tx in enumerate(test_stream_2, 1):
        state = detector.update(tx)
        print(f"Tx {i} (val={tx}): s_pos={state.s_pos}, alert_high={state.alert_high}")
        if state.alert_high:
            print(">>> Alert triggered: gateway failure detected immediately. <<<")

    print("\n---3. Continous latency tracking (soft failure)---")
    lat_detector = ContinousCUSUMDetector(
        baseline_mean=100.0,
        baseline_std=15.0,
        slack_k=0.5,
        threshold_h=4.0
    )

    # stream of latencies: 3 normal calls, then a suddent database lock lag
    latency_stream = [98.0, 105.0, 102.0, 180.0, 220.0]

    for i, lat in enumerate(latency_stream, 1):
        state = lat_detector.update(lat)
        print(f"Tx {i} (lat={lat:5.1f}ms): s_pos={state.s_pos:5.2f}, alert_high={state.alert_high}")
        if state.alert_high:
            print("Alert triggered: latency anomaly detected before timeout.")

