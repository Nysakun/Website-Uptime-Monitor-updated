"""Safety checks: only allow real, public domains and IP addresses."""

import ipaddress
import socket

from .checker import parse_target, resolve_host


class TargetNotAllowed(Exception):
    """Raised when a target must not be checked. Carries an HTTP-style status code."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_target(target):
    """Raise TargetNotAllowed for bad input and private/internal addresses."""
    parsed = parse_target(target)
    if parsed is None:
        raise TargetNotAllowed(
            "Invalid target. Enter a domain (example.com), an IP address "
            "(8.8.8.8) or a full http(s):// URL.",
            400,
        )
    try:
        ip = ipaddress.ip_address(resolve_host(parsed["host"]))
    except (socket.gaierror, UnicodeError):
        return  # unknown domain: the checker reports it as a normal DNS failure
    except ValueError:
        raise TargetNotAllowed("This address cannot be checked.", 403)

    if not ip.is_global:
        raise TargetNotAllowed(
            "Private, local and reserved IP addresses cannot be checked.", 403
        )


def is_allowed(target):
    """True if the target passes validate_target()."""
    try:
        validate_target(target)
    except TargetNotAllowed:
        return False
    return True 