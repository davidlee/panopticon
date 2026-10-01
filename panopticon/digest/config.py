"""Strict parsing of ``digest.toml`` into frozen config (design §5.2 Config, D3, D4).

Pure: takes the already-loaded TOML dict. An unknown key at any level is an
error, so a typo cannot silently drop the denylist and a literal ``api_key``
is refused. Secrets come only from the environment variable named by
``api_key_env``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from panopticon.digest.gate import (
    DEFAULT_DENY,
    GateConfig,
    normalise_deny_entry,
    normalise_host,
)

_MISSING = object()
_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
_POS_INT = "a positive integer"
_STR = "a non-empty string"
_HOSTS = "a list of hostnames (lowercase ASCII; punycode for IDN)"
_DENY = "a list of hostnames, each with an optional /path prefix"


class ConfigError(ValueError):
    """The config is malformed. The message names the key, never its value."""


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: str
    api_key_env: str
    max_input_chars: int
    max_output_tokens: int


@dataclass(frozen=True)
class DigestConfig:
    enabled: bool
    max_pages_per_run: int
    gate: GateConfig
    provider: ProviderConfig


def parse_config(raw: Mapping[str, Any]) -> DigestConfig:
    """Validate ``raw`` and build a :class:`DigestConfig`. Raises :class:`ConfigError`."""
    top = _table(raw, "", {"enabled", "max_pages_per_run", "gate", "digest"})
    return DigestConfig(
        enabled=_field(top, "", "enabled", False, _is_bool, "a boolean"),
        max_pages_per_run=_field(top, "", "max_pages_per_run", 50, _is_positive_int, _POS_INT),
        gate=_parse_gate(top.get("gate", {})),
        provider=_parse_provider(top.get("digest", _MISSING)),
    )


def _parse_gate(raw: Any) -> GateConfig:
    t = _table(raw, "gate", {"deny", "allow", "min_chars", "min_quality"})
    allow = _field(t, "gate", "allow", None, _is_list_of(normalise_host), _HOSTS)
    deny = _field(t, "gate", "deny", [], _is_list_of(normalise_deny_entry), _DENY)
    return GateConfig(
        deny=DEFAULT_DENY | _normalised(deny, normalise_deny_entry),
        allow=None if allow is None else _normalised(allow, normalise_host),
        min_chars=_field(t, "gate", "min_chars", 1500, _is_positive_int, _POS_INT),
        min_quality=float(
            _field(t, "gate", "min_quality", 0.7, _is_positive_number, "a positive number")
        ),
    )


def _parse_provider(raw: Any) -> ProviderConfig:
    if raw is _MISSING:
        raise ConfigError("digest: missing table (digest.model is required)")
    keys = {"endpoint", "model", "api_key_env", "max_input_chars", "max_output_tokens"}
    t = _table(raw, "digest", keys)
    return ProviderConfig(
        endpoint=_field(t, "digest", "endpoint", _OPENROUTER, _is_https_url, "an https:// URL"),
        model=_field(t, "digest", "model", _MISSING, _is_nonempty_str, _STR),
        api_key_env=_field(
            t, "digest", "api_key_env", "OPENROUTER_API_KEY", _is_nonempty_str, _STR
        ),
        max_input_chars=_field(t, "digest", "max_input_chars", 24000, _is_positive_int, _POS_INT),
        max_output_tokens=_field(
            t, "digest", "max_output_tokens", 1500, _is_positive_int, _POS_INT
        ),
    )


def _key_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _table(raw: Any, path: str, known: set[str]) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: expected a table")
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"{_key_path(path, unknown[0])}: unknown key")
    return raw


def _field(
    table: Mapping[str, Any],
    path: str,
    key: str,
    default: Any,
    valid: Callable[[Any], bool],
    what: str,
) -> Any:
    """``table[key]`` if valid, else ``default`` when absent (``_MISSING`` = required)."""
    if key not in table:
        if default is _MISSING:
            raise ConfigError(f"{_key_path(path, key)}: required")
        return default
    if not valid(table[key]):
        raise ConfigError(f"{_key_path(path, key)}: expected {what}")
    return table[key]


def _normalised(entries: list[str], normalise: Callable[[str], str | None]) -> frozenset[str]:
    """Normalise entries already validated by :func:`_is_list_of`."""
    return frozenset(n for e in entries if (n := normalise(e)))


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_positive_int(v: Any) -> bool:
    # bool is a subclass of int, and tomllib yields True/False
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _is_positive_number(v: Any) -> bool:
    return (isinstance(v, float) and v > 0) or _is_positive_int(v)


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v != ""


def _is_https_url(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        parts = urlsplit(v)
        return parts.scheme == "https" and bool(parts.hostname)
    except ValueError:
        return False


def _is_list_of(normalise: Callable[[str], str | None]) -> Callable[[Any], bool]:
    """A validator: a list of strings that each ``normalise``."""
    return lambda v: (
        isinstance(v, list) and all(isinstance(e, str) and normalise(e) is not None for e in v)
    )
