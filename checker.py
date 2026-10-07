"""Checks a single target (domain, IP address or URL) and returns the result."""

import ipaddress
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5
HEADERS = {"User-Agent": "UptimeMonitor/1.0"}

# A valid domain: labels separated by dots, ending in a TLD that starts with a letter
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$",
    re.IGNORECASE,
)


def _as_ip(value):
    """Return an ip object if `value` is an IPv4/IPv6 address, else None."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def parse_target(text):
    """Understand what the user typed.

    Returns a dictionary with:
      type -> "ip" or "domain"
      host -> the domain or IP on its own (no port, no path)
      urls -> list of URLs to try, in order
    or None if the text is not a valid domain / IP / URL.
    """
    text = (text or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return None

    # Bare IPv6 (2001:db8::1) contains colons, so check it before URL parsing
    bare_ip = _as_ip(text.strip("[]"))
    if bare_ip is not None:
        host_text = f"[{bare_ip}]" if bare_ip.version == 6 else str(bare_ip)
        return {
            "type": "ip",
            "host": str(bare_ip),
            "urls": [f"https://{host_text}", f"http://{host_text}"],
        }

    has_scheme = text.lower().startswith(("http://", "https://"))
    try:
        parsed = urlparse(text if has_scheme else "//" + text)
        _ = parsed.port  # raises ValueError for a bad port like :99999
    except ValueError:
        return None

    host = parsed.hostname
    if not host:
        return None

    ip = _as_ip(host)
    if ip is not None:
        kind, host = "ip", str(ip)
    elif DOMAIN_RE.match(host):
        kind = "domain"
    else:
        return None

    urls = [text] if has_scheme else [f"https://{text}", f"http://{text}"]
    return {"type": kind, "host": host, "urls": urls}


def resolve_host(host):
    """Ask DNS for the IP address of a host (an IP is returned as it is)."""
    return socket.getaddrinfo(host, None)[0][4][0]


def _host_is_public(host):
    """True only if `host` resolves to a public, routable IP address."""
    try:
        ip = ipaddress.ip_address(resolve_host(host))
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    return ip.is_global


def _request_once(url):
    """Follow one target, hopping through redirects ourselves so every hop
    can be checked. Returns a dictionary describing what happened.

    kind tells us the type of failure: None (success), "http", "timeout",
    "ssl", "connection", "blocked", "redirects" or "other".
    """
    outcome = {
        "status_code": None,
        "response_time_ms": None,
        "error": None,
        "kind": None,
    }
    start = time.perf_counter()
    try:
        session = requests.Session()
        current_url = url

        for hop in range(MAX_REDIRECTS + 1):
            host = urlparse(current_url).hostname
            if not host or not _host_is_public(host):
                outcome["error"] = "Redirected to a private or unreachable address"
                outcome["kind"] = "blocked"
                return outcome

            response = session.get(
                current_url, timeout=TIMEOUT_SECONDS, headers=HEADERS,
                allow_redirects=False,  # we follow redirects ourselves, one hop at a time
            )

            if response.is_redirect and hop < MAX_REDIRECTS:
                location = response.headers.get("Location")
                if not location:
                    break
                current_url = urljoin(current_url, location)
                continue

            outcome["response_time_ms"] = round((time.perf_counter() - start) * 1000)
            outcome["status_code"] = response.status_code
            if not 200 <= response.status_code < 400:
                outcome["error"] = f"HTTP {response.status_code} {response.reason}"
                outcome["kind"] = "http"
            return outcome

        outcome["error"] = "Too many redirects"
        outcome["kind"] = "redirects"
        return outcome

    except requests.exceptions.Timeout:
        outcome["error"] = f"Timed out after {TIMEOUT_SECONDS}s"
        outcome["kind"] = "timeout"
    except requests.exceptions.SSLError:
        outcome["error"] = "SSL certificate error"
        outcome["kind"] = "ssl"
    except requests.exceptions.ConnectionError:
        outcome["error"] = "Can't connect (server offline or port closed)"
        outcome["kind"] = "connection"
    except requests.exceptions.RequestException as e:
        outcome["error"] = f"Request failed: {e}"
        outcome["kind"] = "other"

    return outcome


def _apply(result, url, outcome):
    """Copy the outcome of one request into the final result."""
    result["checked_url"] = url
    result["status_code"] = outcome["status_code"]
    result["response_time_ms"] = outcome["response_time_ms"]
    result["error"] = outcome["error"]
    result["error_kind"] = outcome["kind"]
    result["is_up"] = outcome["error"] is None


def check_website(target):
    """Check one domain / IP / URL and return a dictionary describing the result."""
    result = {
        "url": target,            # exactly what the user typed (database key)
        "target_type": None,      # "ip" or "domain"
        "resolved_ip": None,      # the IP address DNS gave us
        "checked_url": None,      # the URL that was really requested
        "is_up": False,
        "status_code": None,
        "response_time_ms": None,
        "error": None,
        "error_kind": None,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # Step 1: understand the input
    parsed = parse_target(target)
    if parsed is None:
        result["error"] = "Invalid target (use a domain, IP address or http(s):// URL)"
        result["error_kind"] = "invalid"
        return result
    result["target_type"] = parsed["type"]

    # Step 2: DNS lookup
    try:
        result["resolved_ip"] = resolve_host(parsed["host"])
    except (socket.gaierror, UnicodeError):
        result["error"] = "DNS lookup failed (domain not found)"
        result["error_kind"] = "dns"
        return result

    # Step 3: request. Try https first, then http, but only when the
    # failure is an SSL/connection problem (not a timeout or HTTP error).
    first_failure = None
    for url in parsed["urls"]:
        outcome = _request_once(url)
        if outcome["kind"] not in ("ssl", "connection"):
            _apply(result, url, outcome)
            break
        if first_failure is None:
            first_failure = (url, outcome)
    else:
        _apply(result, *first_failure)

    return result


if __name__ == "__main__":
    samples = [
        "google.com",
        "https://github.com/",
        "8.8.8.8",
        "2001:4860:4860::8888",
        "example.com:8080",
        "not-a-valid-url",
        "999.1.1.1",
    ]
    for sample in samples:
        print(f"{sample:<26} -> {parse_target(sample)}") 