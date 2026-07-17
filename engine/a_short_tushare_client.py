"""Pinned, fail-closed Tushare initialization for A-short provider callers."""
from __future__ import annotations

import os


SUPPORTED_TUSHARE_VERSION = "1.4.29"
DEFAULT_TUSHARE_BASE_URL = "https://api.tushare.pro/dataapi"
_DATA_API_URL_ATTRIBUTE = "_DataApi__http_url"


def is_retryable_tushare_error(exc: Exception) -> bool:
    """Return true only for transport failures and explicit rate limiting.

    Permission, entitlement, malformed-request, and schema errors must surface
    immediately rather than consuming retries or being misclassified as a
    transient provider incident.
    """
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    error_name = type(exc).__name__.lower()
    if any(token in error_name for token in (
        "timeout", "connectionerror", "proxyerror", "chunkedencodingerror",
        "remotedisconnected", "temporarilyunavailable",
    )):
        return True
    message = str(exc).lower()
    return any(token in message for token in (
        "rate limit", "too many requests", "http 429", "status 429",
        "频率限制", "请求过于频繁", "限流", "每分钟最多访问",
    ))


def _require_supported_version(ts_module) -> None:
    version = getattr(ts_module, "__version__", None)
    if version != SUPPORTED_TUSHARE_VERSION:
        raise RuntimeError(
            f"unsupported Tushare runtime {version!r}; A-short requires "
            f"tushare=={SUPPORTED_TUSHARE_VERSION} because its endpoint pin uses "
            "a verified private DataApi layout"
        )


def pin_tushare_base_url(ts_module) -> None:
    """Apply the verified endpoint pin or fail before any provider client exists."""
    _require_supported_version(ts_module)
    try:
        data_api = ts_module.pro.client.DataApi
    except AttributeError as exc:
        raise RuntimeError(
            "unsupported Tushare runtime: tushare.pro.client.DataApi is unavailable; "
            "refusing to use an unpinned default endpoint"
        ) from exc
    if not hasattr(data_api, _DATA_API_URL_ATTRIBUTE):
        raise RuntimeError(
            f"unsupported Tushare runtime: DataApi lacks {_DATA_API_URL_ATTRIBUTE}; "
            "refusing to use an unpinned default endpoint"
        )

    base_url = os.environ.get("TUSHARE_BASE_URL", DEFAULT_TUSHARE_BASE_URL)
    try:
        setattr(data_api, _DATA_API_URL_ATTRIBUTE, base_url)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError(
            "unsupported Tushare runtime: cannot pin DataApi endpoint; "
            "refusing to create a provider client"
        ) from exc
    if getattr(data_api, _DATA_API_URL_ATTRIBUTE, None) != base_url:
        raise RuntimeError(
            "unsupported Tushare runtime: DataApi endpoint pin did not persist; "
            "refusing to create a provider client"
        )


def init_tushare_pro(token: str, ts_module=None):
    """Return a direct-token `pro_api` client after the pinned runtime contract passes.

    `ts.set_token` is intentionally never called because it writes a process-global
    token cache. `ts_module` is injectable for offline contract tests.
    """
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the A-short Tushare client")
    if ts_module is None:
        import tushare as ts_module  # noqa: PLC0415
    pin_tushare_base_url(ts_module)
    return ts_module.pro_api(token)
