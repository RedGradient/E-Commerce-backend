from prometheus_client import Counter, Histogram

# HTTP
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Stripe webhooks
webhook_events_total = Counter(
    "webhook_events_total",
    "Stripe webhook events by type and outcome",
    ["event_type", "outcome"],
)

# Outbox publisher
outbox_publish_total = Counter(
    "outbox_publish_total",
    "Outbox messages published to RabbitMQ",
    ["event_type", "result"],
)

outbox_publish_duration_seconds = Histogram(
    "outbox_publish_duration_seconds",
    "Outbox publish duration in seconds",
    ["event_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    status = str(status_code)
    http_requests_total.labels(method=method, path=path, status=status).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(
        duration_seconds
    )


def record_webhook_event(*, event_type: str, outcome: str) -> None:
    webhook_events_total.labels(event_type=event_type, outcome=outcome).inc()


def record_outbox_publish(
    *,
    event_type: str,
    result: str,
    duration_seconds: float | None = None,
) -> None:
    outbox_publish_total.labels(event_type=event_type, result=result).inc()
    if duration_seconds is not None:
        outbox_publish_duration_seconds.labels(event_type=event_type).observe(
            duration_seconds
        )
