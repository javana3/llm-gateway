from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "gateway_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "gateway_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["path"],
)
CACHE_HITS = Counter("gateway_cache_hits_total", "Semantic cache hits")
CACHE_MISSES = Counter("gateway_cache_misses_total", "Semantic cache misses")
TOKENS = Counter("gateway_tokens_total", "Total billed tokens")
