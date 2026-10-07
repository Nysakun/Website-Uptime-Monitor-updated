"""Turns a raw check result into a plain-language explanation of the problem."""

SLOW_MS = 3000


def _msg(level, title, detail, suggestion=""):
    return {"level": level, "title": title, "detail": detail, "suggestion": suggestion}


def _http_message(code):
    """Explain an HTTP error status (the server replied, but with an error)."""
    if code in (401, 403):
        return _msg(
            "error", "Access denied",
            f"The server is running but refused the request (HTTP {code}).",
            "The page may need a login, or the site may block automated checks. "
            "Try the home page instead.",
        )
    if code == 404:
        return _msg(
            "error", "Page not found",
            "The server is reachable, but this page does not exist (HTTP 404).",
            "Check the address for typos. The server itself is responding.",
        )
    if code == 429:
        return _msg(
            "error", "Too many requests",
            "The server is limiting how often it can be checked (HTTP 429).",
            "Wait a few minutes and try again.",
        )
    if code == 503:
        return _msg(
            "error", "Service unavailable",
            "The server is overloaded or down for maintenance (HTTP 503).",
            "Try again later. If it keeps happening, contact the site owner.",
        )
    if code in (502, 504):
        return _msg(
            "error", "Gateway problem",
            f"A server in front of the website could not get a reply from the "
            f"main server (HTTP {code}).",
            "This is usually temporary. Try again in a few minutes.",
        )
    if code is not None and code >= 500:
        return _msg(
            "error", "Server error",
            f"The website's server failed while handling the request (HTTP {code}).",
            "The problem is on the website's side. Try again later.",
        )
    return _msg(
        "error", "Request rejected",
        f"The server replied with an error (HTTP {code}).",
        "Check the address and try again.",
    )


def diagnose(result):
    """Return {level, title, detail, suggestion} for one check result.

    level is "ok", "warning" or "error".
    """
    kind = result.get("error_kind")

    if result.get("is_up"):
        ms = result.get("response_time_ms")
        if ms is not None and ms > SLOW_MS:
            return _msg(
                "warning", "Working, but slow",
                f"The website replied in {ms} ms, which is slower than normal.",
                "This can be a busy server or a slow network. Check again in a few minutes.",
            )
        return _msg(
            "ok", "Everything looks good",
            "The website replied normally and quickly.",
        )

    if kind == "invalid":
        return _msg(
            "error", "Not a valid address",
            "This is not a valid domain name or IP address.",
            "Use a domain like example.com or an IP like 8.8.8.8.",
        )
    if kind == "dns":
        return _msg(
            "error", "Domain not found",
            "The domain name could not be translated into an IP address (DNS lookup failed).",
            "Check the spelling. If it is correct, the domain may have expired "
            "or its DNS settings may be broken.",
        )
    if kind == "timeout":
        return _msg(
            "error", "Website is not responding in time",
            "The server did not answer within the time limit.",
            "The server may be overloaded or down, or a network problem is blocking "
            "the connection. Try again in a minute.",
        )
    if kind == "ssl":
        return _msg(
            "error", "Security certificate problem",
            "The secure (HTTPS) connection could not be trusted.",
            "The certificate may be expired, issued for a different name, or self-signed. "
            "For a bare IP address this is common, because certificates are made for domain names.",
        )
    if kind == "blocked":
        return _msg(
            "error", "Redirected to a blocked address",
            "This website tried to redirect the check to a private, local or "
            "reserved network address.",
            "This is blocked for security reasons, since following it could "
            "expose an internal network. The website itself may be misconfigured.",
        )
    if kind == "connection":
        return _msg(
            "error", "Cannot connect to the server",
            "The address exists, but nothing accepted the connection.",
            "The server may be offline, or a firewall may be blocking it.",
        )
    if kind == "redirects":
        return _msg(
            "error", "Redirect loop",
            "The website keeps sending visitors from one address to another forever.",
            "The site's redirect settings need fixing by its owner.",
        )
    if kind == "http":
        return _http_message(result.get("status_code"))

    return _msg(
        "error", "Check failed",
        result.get("error") or "An unknown problem occurred.",
        "Try again in a minute.",
    ) 