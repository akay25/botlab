"""Values shared across the detection engine and the routes."""

# The order a production stack meets a client. `first_catching_layer` reads
# this list from the top, so the earliest layer that flags a client is the one
# reported. Consistency sits last because it needs every other layer first.
LAYERS = [
    "network",
    "tls",
    "http",
    "browser",
    "worlds",
    "runtime",
    "environment",
    "behavior",
    "consistency",
]

# Score bands. The 1 to 99 range copies the convention commercial systems use,
# so results map onto their published thresholds.
VERDICT_BANDS = [
    (10, "automated"),
    (30, "likely automated"),
    (60, "unclear"),
    (99, "likely human"),
]

# A run token is the session id the task page is served and reports back with.
TOKEN_LENGTH = 12

CSV_COLUMNS = (
    [
        "time",
        "id",
        "label",
        "ip",
        "score",
        "verdict",
        "first_catching_layer",
        "strongest_layer",
        "total_weight",
        "ja4",
        "ja3",
        "user_agent",
    ]
    + ["w_" + name for name in LAYERS]
    + ["detection_ids", "source", "header_source", "page_url", "divergences"]
)
