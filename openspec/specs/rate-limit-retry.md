# Spec: SerpAPI Adapter — Rate Limiting & Retry

## REQ-11: Rate Limiting

**Given** rate_limit_rps = 2.0 (min_interval = 0.5s),
**When** two consecutive `_fetch_page()` calls are made,
**Then** at least 0.5s elapses between actual HTTP requests.

## REQ-12: Retry on Transient Errors

**Given** SerpAPI returns HTTP 429/500/503,
**When** `_fetch_page()` is called,
**Then** retries up to 3 times with exponential backoff (1s, 2s, 4s base + jitter).

## REQ-13: No Retry on Auth Errors

**Given** SerpAPI returns HTTP 401 or 403,
**When** `_fetch_page()` is called,
**Then** raises immediately without retry.

## REQ-14: API Error in 200 Response

**Given** SerpAPI returns HTTP 200 but `search_metadata.status != "Success"`,
**When** response is processed,
**Then** treats as error (uses `error` field from response body).

## REQ-15: Timeout

**Given** `timeout_s = 20.0`,
**When** SerpAPI does not respond within 20 seconds,
**Then** treats as transient error (retryable).

---

## PBT Properties

### PROP-10: Retry Count Bound
**Invariant**: Total fetch attempts per page <= `max_retries + 1` (= 4).
**Falsification**: Mock always-failing server; count attempts; assert <= 4.

### PROP-11: Backoff Monotonicity
**Invariant**: Each retry delay is >= previous delay's base (ignoring jitter).
**Falsification**: Record delays across retries; assert base component is non-decreasing.

### PROP-12: Rate Limit Interval
**Invariant**: Time between any two consecutive HTTP requests >= `min_interval - epsilon` (epsilon = 10ms for scheduling jitter).
**Falsification**: Fire N rapid requests; record timestamps; assert min gap.
