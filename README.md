# Smart Payment Router

A lightweight, cost-aware payment routing service built with python and FastAPI. It routes incoming payments across multiple acquirers using dynamic loss optimization, tracks performance drift using sequential CUSUM algorithms, and models availability through discrete Markov Chains.

## Core Mathematics

### 1. Cost Function
Picks the gateway with the lowest total score:

$$J = w_1 \cdot \text{Fee} + w_2 \cdot \text{Latency} + w_3 \cdot \text{Risk}$$

### 2. CUSUM Anomaly Detection
* **Failure spikes (Binary):**
  $$S_n = \max(0, S_{n-1} + z_n)$$

* **Latency drift (Continuous):**

  $$S_n^+ = \max\left(0, S_{n-1}^+ + \frac{L_n - \mu}{\sigma} - k\right)$$

  Trips gateway to `DEGRADED` when $S^+_n \ge h$.

### 3. Markov Reliability
Models state transitions across $\{H, D, P\}$:

$$P = \begin{bmatrix} 1 - p_{\text{trip}} & p_{\text{trip}} & 0 \\ 0 & 1 - p_{\text{probe}} & p_{\text{probe}} \\ p_{\text{heal}} & 1 - p_{\text{heal}} & 0 \end{bmatrix}$$

Solves steady-state availability via $\boldsymbol{\pi} P = \boldsymbol{\pi}$.

## Project Structure

```text
├── api.py               # FastAPI endpoints (/route, /feedback, /metrics)
├── router_engine.py     # Routing loss logic & CUSUM state trackers
├── markov_model.py      # DTMC matrix solver & transition tracker
├── mock_gateway.py      # Synthetic acquirer behavior & latency injection
├── simulation_bench.py  # End-to-end chaos run & empirical verification
├── test_router.py       # Core engine & Markov unit tests
└── test_api.py          # FastAPI endpoint integration tests
