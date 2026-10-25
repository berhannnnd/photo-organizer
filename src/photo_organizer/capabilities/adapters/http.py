"""Bounded JSON HTTP transport with classified errors and safe credential references."""

import json
import os
import urllib.error
import urllib.request

from photo_organizer.capabilities.scheduling import provider_slot
from photo_organizer.core.errors import CapabilityError
from photo_organizer.runtime.context import admit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CapabilityError(
            "redirect_refused",
            "Configure the final service endpoint; credential redirects are refused",
        )


def request(config, body, path="", headers=None):
    with provider_slot(config):
        return _request(config, body, path, headers)


def _request(config, body, path="", headers=None):
    credential = config.get("api_key_env")
    key = os.environ.get(credential) if credential else None
    if credential and not key:
        raise CapabilityError(
            "authentication_required", "Configured credential environment variable is missing"
        )
    h = {"Content-Type": "application/json", **(headers or {})}
    if key:
        h["Authorization"] = "Bearer " + key
    if config["protocol"] == "anthropic" and key:
        h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    req = urllib.request.Request(
        config["endpoint"].rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=h,
    )
    if body is not None:
        admit(remote=True)
    try:
        with urllib.request.build_opener(NoRedirect).open(
            req, timeout=config.get("timeout", 90)
        ) as response:
            data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise CapabilityError("invalid_response", "Model response exceeds byte budget")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise CapabilityError("invalid_response", "Provider JSON must be an object")
            return value
    except urllib.error.HTTPError as e:
        status = e.code
        retry_after = e.headers.get("Retry-After")
        delay = None
        if retry_after:
            try:
                delay = max(0, float(retry_after))
            except ValueError:
                import datetime
                from email.utils import parsedate_to_datetime

                try:
                    delay = max(
                        0,
                        (
                            parsedate_to_datetime(retry_after)
                            - datetime.datetime.now(datetime.timezone.utc)
                        ).total_seconds(),
                    )
                except (ValueError, TypeError, OverflowError):
                    pass
        import math

        if delay is not None and not math.isfinite(delay):
            delay = None
        e.close()
        code = {
            401: "authentication_failed",
            403: "permission_denied",
            404: "model_or_endpoint_missing",
            429: "rate_limited",
            400: "unsupported_input",
        }.get(status, "provider_failed")
        raise CapabilityError(
            code, "Provider HTTP " + str(status), status == 429 or status >= 500, retry_after=delay
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise CapabilityError(
            "unreachable", "Provider unavailable or timed out; billing outcome may be unknown", True
        ) from None
    except (json.JSONDecodeError, UnicodeError):
        raise CapabilityError("invalid_response", "Provider did not return valid JSON") from None
