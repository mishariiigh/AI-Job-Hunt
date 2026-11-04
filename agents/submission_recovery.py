def classify_timeout(stage):
    # stage: before_send or after_send_unknown
    if stage == "before_send":
        return "RETRY_SAFE"
    return "UNKNOWN_OUTCOME"

def handle_http(status):
    if status == 429:
        return "RATE_LIMITED"
    if 500 <= status <= 599:
        return "SERVER_ERROR"
    if 400 <= status <= 499:
        return "CLIENT_ERROR"
    return "OK"
