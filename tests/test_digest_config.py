"""Tests for strict digest config parsing (design §5.2 Config, D3, D4)."""

from __future__ import annotations

import copy
import tomllib
from typing import Any

import pytest

from panopticon.digest.config import ConfigError, parse_config
from panopticon.digest.gate import DEFAULT_DENY

EXAMPLE = """
enabled = true
max_pages_per_run = 50

[gate]
deny  = ["mybank.example"]
allow = ["lwn.net", "Example.ORG."]
min_chars = 1500
min_quality = 0.7

[digest]
endpoint = "https://openrouter.ai/api/v1/chat/completions"
model = "vendor/model"
api_key_env = "OPENROUTER_API_KEY"
max_input_chars = 24000
max_output_tokens = 1500
"""


def example() -> dict[str, Any]:
    return tomllib.loads(EXAMPLE)


def with_(path: str, value: Any) -> dict[str, Any]:
    """The example with the dotted ``path`` set to ``value`` (a fresh copy)."""
    raw = copy.deepcopy(example())
    *parents, leaf = path.split(".")
    node = raw
    for key in parents:
        node = node[key]
    node[leaf] = value
    return raw


def without(path: str) -> dict[str, Any]:
    raw = copy.deepcopy(example())
    *parents, leaf = path.split(".")
    node = raw
    for key in parents:
        node = node[key]
    del node[leaf]
    return raw


def rejects(raw: dict[str, Any], match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        parse_config(raw)


def test_parses_the_design_example():
    cfg = parse_config(example())
    assert cfg.enabled is True
    assert cfg.max_pages_per_run == 50
    assert cfg.gate.deny == DEFAULT_DENY | {"mybank.example"}
    assert cfg.gate.allow == frozenset({"lwn.net", "example.org"})
    assert cfg.gate.min_chars == 1500
    assert cfg.gate.min_quality == 0.7
    assert cfg.provider.endpoint == "https://openrouter.ai/api/v1/chat/completions"
    assert cfg.provider.model == "vendor/model"
    assert cfg.provider.api_key_env == "OPENROUTER_API_KEY"
    assert cfg.provider.max_input_chars == 24000
    assert cfg.provider.max_output_tokens == 1500


def test_minimal_config_takes_defaults():
    cfg = parse_config({"digest": {"model": "vendor/model"}})
    assert cfg.enabled is False
    assert cfg.max_pages_per_run == 50
    assert cfg.gate.deny == DEFAULT_DENY
    assert cfg.gate.allow is None
    assert (cfg.gate.min_chars, cfg.gate.min_quality) == (1500, 0.7)
    assert cfg.provider.endpoint == "https://openrouter.ai/api/v1/chat/completions"
    assert cfg.provider.api_key_env == "OPENROUTER_API_KEY"
    assert (cfg.provider.max_input_chars, cfg.provider.max_output_tokens) == (24000, 1500)


def test_integer_min_quality_is_accepted():
    assert parse_config(with_("gate.min_quality", 1)).gate.min_quality == 1.0


@pytest.mark.parametrize("path", ["enabeld", "gate.denny", "digest.modle"])
def test_rejects_an_unknown_key_at_each_level(path: str):
    rejects(with_(path, "x"), "unknown key")


@pytest.mark.parametrize("path", ["api_key", "digest.api_key", "gate.api_key"])
def test_rejects_a_literal_api_key(path: str):
    rejects(with_(path, "sk-secret"), "unknown key")


def test_error_does_not_echo_a_literal_api_key_value():
    with pytest.raises(ConfigError) as err:
        parse_config(with_("digest.api_key", "sk-secret"))
    assert "sk-secret" not in str(err.value)


def test_rejects_an_unknown_table():
    rejects(with_("triage", {"model": "x"}), "unknown key")


@pytest.mark.parametrize(
    "endpoint",
    ["http://openrouter.ai/api/v1/chat/completions", "ftp://x.org/", "openrouter.ai", "https://"],
)
def test_rejects_a_non_https_endpoint(endpoint: str):
    rejects(with_("digest.endpoint", endpoint), "endpoint")


def test_rejects_a_missing_model():
    rejects(without("digest.model"), "model")


def test_rejects_a_missing_digest_table():
    rejects(without("digest"), "digest")


@pytest.mark.parametrize("model", ["", 3])
def test_rejects_a_bad_model(model: Any):
    rejects(with_("digest.model", model), "model")


@pytest.mark.parametrize(
    "path",
    [
        "max_pages_per_run",
        "gate.min_chars",
        "gate.min_quality",
        "digest.max_input_chars",
        "digest.max_output_tokens",
    ],
)
@pytest.mark.parametrize("value", [True, False, 0, -1, "10"])
def test_rejects_bool_non_positive_or_non_numeric(path: str, value: Any):
    rejects(with_(path, value), path)


@pytest.mark.parametrize("path", ["max_pages_per_run", "gate.min_chars", "digest.max_input_chars"])
def test_rejects_a_float_in_an_integer_field(path: str):
    rejects(with_(path, 10.5), path)


def test_rejects_a_non_bool_enabled():
    rejects(with_("enabled", 1), "enabled")


@pytest.mark.parametrize("field", ["deny", "allow"])
@pytest.mark.parametrize("entry", ["faß.de", "https://bank.com", "a..b", "", "bad host.com"])
def test_rejects_a_non_normalisable_domain_entry(field: str, entry: str):
    rejects(with_(f"gate.{field}", ["ok.example", entry]), f"gate.{field}")


def test_deny_takes_a_path_prefix_and_allow_does_not():
    cfg = parse_config(with_("gate.deny", ["GitHub.com/Acme/"]))
    assert "github.com/acme" in cfg.gate.deny
    rejects(with_("gate.allow", ["github.com/acme"]), "gate.allow")
    rejects(with_("gate.deny", ["github.com/a?b"]), "gate.deny")


@pytest.mark.parametrize("field", ["deny", "allow"])
@pytest.mark.parametrize("value", ["bank.com", [3], None])
def test_rejects_a_domain_list_of_the_wrong_type(field: str, value: Any):
    rejects(with_(f"gate.{field}", value), f"gate.{field}")


@pytest.mark.parametrize("value", ["", 3])
def test_rejects_a_bad_api_key_env(value: Any):
    rejects(with_("digest.api_key_env", value), "api_key_env")


@pytest.mark.parametrize("path", ["gate", "digest"])
def test_rejects_a_table_of_the_wrong_type(path: str):
    rejects(with_(path, "x"), path)
