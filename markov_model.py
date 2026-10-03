from typing import Dict, Tuple
import numpy as np

class GatewayMarkovModel:
    STATES = ["HEALTHY", "DEGRADED", "PROBING"]
    def __init__(self, p_trip: float = 0.05, p_probe: float = 0.40, p_heal: float = 0.70):
        self.p_trip = p_trip
        self.p_probe = p_probe
        self.p_heal = p_heal

        self.transition_counts = np.zeros((3, 3), dtype=np.int64)

    @property
    def theoretical_transition_matrix(self) -> np.ndarray:
        return np.array([
            [1.0 - self.p_trip, self.p_trip, 0.0],
            [0.0, 1.0 - self.p_probe, self.p_probe],
            [self.p_heal, 1.0 - self.p_heal, 0.0]
        ])
    def solve_stationary_distribution(self) -> Dict[str, float]:
        P = self.theoretical_transition_matrix
        A = P.T - np.eye(3)
        A[-1] = [1.0, 1.0, 1.0]
        b = np.array([0.0, 0.0, 1.0])

        pi = np.linalg.solve(A, b)
        return {
            "pi_healthy": float(pi[0]),
            "pi_degraded": float(pi[1]),
            "pi_probing": float(pi[2])
        }

    def record_state_transition(self, from_state: str, to_state: str) -> None:
        idx_from = self.STATES.index(from_state)
        idx_to = self.STATES.index(to_state)
        self.transition_counts[idx_from, idx_to] += 1

    def get_empirical_transition_matrix(self) -> np.ndarray:
        row_sums = self.transition_counts.sum(axis=1, keepdims=True)
        with np.errstate(divide='ignore', invalid='ignore'):
            empirical_P = np.true_divide(self.transition_counts, row_sums)
            empirical_P[~np.isfinite(empirical_P)] = 0.0
        return empirical_P
