# Smart Payment Router

[![CI Test Suite](https://github.com/deependra675/Fintech_Smart_Router/actions/workflows/ci.yml/badge.svg)](https://github.com/deependra675/Fintech_Smart_Router/actions/workflows/ci.yml)

An adaptive payment routing engine built with FastAPI and NumPy. Instead of static priority lists or naive round-robin, it routes transactions across multiple acquirers (Cashfree, Razorpay, Stripe) using a dynamic loss function, statistical drift detection (CUSUM + Welford's algorithm), in-flight cascading failover, and idempotent request handling.

---

## Why Naive Routing Fails

Most simple payment implementations route either:
1. **Statically by fee:** They always pick the cheapest provider until it completely goes down, incurring heavy timeout penalties and dropped checkouts.
2. **Via naive thresholding:** Counting errors in rolling time windows (e.g., "trip circuit breaker if 5 errors occur in 60s"). This either triggers false alarms on isolated user card declines or reacts too slowly to sudden upstream outages.

This router addresses both issues:
- **Noise vs. Outage distinction:** Uses two-sided cumulative sum (CUSUM) control charts to absorb random user-side card declines while tripping immediately on consecutive gateway outages.
- **Pre-timeout degradation detection:** Tracks latency variance continuously using Welford's algorithm. If an acquirer's database locks and average latency drifts upward, the router penalizes its composite score before transactions start hitting hard 504 timeouts.
- **Safe fallback & idempotency:** If a gateway returns a 5xx during processing, the engine immediately cascades the charge to the next best provider in-flight without double-billing, enforced by client-supplied `Idempotency-Key` headers.

---

## Core Routing Logic

### 1. Composite Cost Optimization
At each routing decision, the engine evaluates available healthy gateways by minimizing:

$$J = w_1 \cdot \text{Fee} + w_2 \cdot \text{Latency} + w_3 \cdot \text{Risk}$$

* $\text{Fee}$: Scaled MDR basis points (Cashfree: 1.5%, Razorpay: 1.8%, Stripe: 2.0%).
* $\text{Latency}$: Running mean response latency normalized against baseline.
* $\text{Risk}$: Combined cumulative drift score ($S^+_{\text{failure}} + S^+_{\text{latency}}$).

### 2. Anomaly Detection (CUSUM + Welford)

* **Binary Failure Detector:**
  Accumulates deviations from the target failure rate ($\mu_0 = 0.02$) with slack $k = 0.03$:
  $$S_n^+ = \max(0, S_{n-1}^+ + (x_n - \mu_0 - k))$$
  Isolated user errors decay back to 0. Burst failures accumulate past threshold $h = 1.0$ and trip the gateway to `DEGRADED`.

* **Continuous Latency Drift:**
  Uses Welford's online variance algorithm to maintain dynamic baseline mean ($\mu$) and standard deviation ($\sigma$) in memory ($O(1)$ space). Standardized Z-scores drive upper CUSUM accumulation:
  $$Z_n = \frac{L_n - \mu}{\sigma}, \quad S_n^+ = \max(0, S_{n-1}^+ + (Z_n - k))$$
  Samples where $S_n^+ \ge h$ are excluded from updating the baseline to prevent poison drift.

### 3. Reliability & Recovery (Discrete Markov Model)
Gateways operate across three states: `HEALTHY` ($H$), `DEGRADED` ($D$), and `PROBING` ($P$). 

State transitions follow the matrix:

$$P = \begin{bmatrix} 1 - p_{\text{trip}} & p_{\text{trip}} & 0 \\ 0 & 1 - p_{\text{probe}} & p_{\text{probe}} \\ p_{\text{heal}} & 1 - p_{\text{heal}} & 0 \end{bmatrix}$$

When degraded, the router periodically sends background canary probes. Once an acquirer records $N$ consecutive successful probe responses (streak requirement), the engine resets CUSUM drift scores and restores it to `HEALTHY`. The theoretical steady-state availability vector is computed by solving $\boldsymbol{\pi} P = \boldsymbol{\pi}$ subject to $\sum \pi_i = 1$.

---

## Repository Structure

```text
├── api.py               # FastAPI endpoints (/charge, /route, /feedback, /metrics)
├── router_engine.py     # Routing loss logic & CUSUM state management
├── cusum_detector.py    # Welford variance tracker & CUSUM detectors
├── markov_model.py      # Discrete Markov matrix solver & transition recorder
├── mock_gateway.py      # Acquirer simulation & chaos injection harness
├── simulation_bench.py  # End-to-end chaos traffic simulation script
├── test_router.py       # Math, statistical drift, & failover unit tests
├── test_api.py          # FastAPI endpoint integration & idempotency tests
└── requirements.txt     # Python runtime dependencies
```


# 1. Installation

Clone the repository and navigate to the project directory:

git clone https://github.com/deependra675/Fintech_Smart_Router.git
cd Fintech_Smart_Router


Create and activate a virtual environment.

## Windows PowerShell

python -m venv .venv
.venv\Scripts\Activate.ps1


## Linux / macOS

python -m venv .venv
source .venv/bin/activate


# Install dependencies:

pip install -r requirements.txt

# 2. Run Test Suite

Executes all 10 unit and integration tests across statistical algorithms, failover cascades, and HTTP handlers.

pytest test_router.py test_api.py -v

# 3. Run Chaos Traffic Simulation

Runs a 20-transaction workload with latency spikes, fallback rerouting, and empirical Markov state tracking.

python simulation_bench.py

# 4. Run API Server

Start the FastAPI server using Uvicorn:

uvicorn api:app --reload --port 8000


## Interactive OpenAPI documentation will be available at http://127.0.0.1:8000/docs.

## Quick Reference
### Method	Endpoint	Description
```text
POST	/charge 	    Executes payment with automated failover and replay safety
POST	/route	        Returns the optimal gateway without processing a charge
POST	/feedback	    Accepts gateway telemetry updates
GET	    /metrics	      Reports gateway health and statistical metrics
```
