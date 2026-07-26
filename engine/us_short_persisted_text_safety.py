"""Shared persisted-text safety checks for the inert US-short discovery lane."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit


SECRET_TEXT_RE = re.compile(r"(?:api[_-]?key|secret|password|access[_-]?token|bearer)", re.I)
# A word such as "password manager" is ordinary discovery evidence, not a
# credential.  The persisted-artifact backstop therefore needs a value-shaped
# credential, while callers that reject *queries* may keep the broader lexical
# policy above.
_PERSISTED_CREDENTIAL_VALUE_RE = re.compile(
    r"""(?ix)
    (?:\b(?:api[_-]?key|secret|password|access[_-]?token)\b\s*(?:=|:)\s*[\"']?[^\s,;\"'}\]]+)
    |(?:\bbearer\s+[\"']?[A-Za-z0-9._~+\-/]{6,})
    """
)
_CREDENTIAL_KEY_SUBSTRINGS = (
    "apikey", "token", "secret", "password", "passwd", "credential",
    "bearer", "signature", "privatekey", "sessionid",
)
_CREDENTIAL_KEY_EXACT = frozenset({
    "key", "auth", "authorization", "sig", "session", "sid", "sas", "pwd", "cred", "hmac", "otp",
    "passphrase",
})


def _persisted_strings(value: Any):
    """Yield every persisted string, including map keys that would serialize into an artifact."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str):
                yield key
            yield from _persisted_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _persisted_strings(nested)
    elif isinstance(value, str):
        yield value


def _is_credential_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    compact = re.sub(r"[^a-z0-9]+", "", value.lower())
    return compact in _CREDENTIAL_KEY_EXACT or any(token in compact for token in _CREDENTIAL_KEY_SUBSTRINGS)


def _has_credential_mapping(value: Any) -> bool:
    """Detect an actual credential field without classifying ordinary prose words."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if _is_credential_key(key) and isinstance(nested, str) and nested.strip():
                return True
            if _has_credential_mapping(nested):
                return True
    elif isinstance(value, list):
        return any(_has_credential_mapping(nested) for nested in value)
    return False


def credential_query_keys(query: Any) -> list[str]:
    """Return URL-query keys that structurally denote credentials.

    This is intentionally independent of credential *values*: signed URLs often
    carry no keyword that a whole-text secret scan can recognize.
    """
    if not isinstance(query, str) or not query:
        return []
    hits: list[str] = []
    for key, _value in parse_qsl(query.replace(";", "&"), keep_blank_values=True):
        compact = re.sub(r"[^a-z0-9]+", "", key.lower())
        if compact in _CREDENTIAL_KEY_EXACT or any(token in compact for token in _CREDENTIAL_KEY_SUBSTRINGS):
            hits.append(key)
    return hits


def persisted_text_violation(value: Any) -> str | None:
    """Return a stable reason when a JSON-persisted value carries credential material."""
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return "not_json_serializable"
    if _has_credential_mapping(value) or any(
        _PERSISTED_CREDENTIAL_VALUE_RE.search(persisted)
        for persisted in _persisted_strings(value)
    ):
        return "secret_like_text"
    for persisted in _persisted_strings(value):
        for candidate in re.findall(r"https?://[^\s\"'\\]+", persisted):
            if credential_query_keys(urlsplit(candidate).query):
                return "credential_bearing_locator"
        # A provider/model can supply a locator without a scheme.  The existing
        # receipt ledger treats this exactly as a locator, so frozen packet
        # writers must not leave an escape hatch for `host/path?sig=...`.
        if "?" in persisted and credential_query_keys(persisted.split("?", 1)[1].split("#", 1)[0]):
            return "credential_bearing_locator"
    return None
