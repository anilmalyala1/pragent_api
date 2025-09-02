"""Utilities for comparing configuration dictionaries across environments.

This module exposes :func:`diff_configs` which accepts a mapping of
environment name to configuration data (already parsed from JSON files).
It reports missing keys, differing values between environments and
values that deviate from those defined for the production environment.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping
import json


def _normalize(value: Any) -> str:
    """Normalize potentially unhashable JSON values for comparison.

    Lists and dictionaries are converted to canonical JSON strings so they
    can be compared using standard equality operations.
    """

    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def diff_configs(
    configs: Mapping[str, Mapping[str, Any]],
    prod_env: str = "production",
) -> Dict[str, Any]:
    """Compare configuration dictionaries across environments.

    Parameters
    ----------
    configs:
        Mapping of environment name to its configuration dictionary.
    prod_env:
        Name of the production environment. Differences relative to this
        environment are reported under ``prod_diffs``.

    Returns
    -------
    dict
        A dictionary containing three sections:

        ``missing_keys``
            Mapping of environment name to a list of keys that are absent in
            that environment.
        ``value_diffs``
            Keys whose values differ across environments. Each entry maps the
            key to the value for every environment that provides it.
        ``prod_diffs``
            Keys where at least one environment has a value different from the
            production configuration. Each entry maps the key to a mapping of
            environment names to dictionaries with ``expected`` (production
            value) and ``actual`` (environment value).
    """

    all_keys = set()
    for env_config in configs.values():
        all_keys.update(env_config.keys())

    missing_keys: Dict[str, list[str]] = {env: [] for env in configs}
    value_diffs: Dict[str, Dict[str, Any]] = {}
    prod_diffs: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for key in all_keys:
        present_envs = [env for env, conf in configs.items() if key in conf]
        missing_envs = set(configs) - set(present_envs)
        for env in missing_envs:
            missing_keys[env].append(key)

        values = {env: configs[env][key] for env in present_envs}
        normalized = {_normalize(v) for v in values.values()}
        if len(normalized) > 1:
            value_diffs[key] = values

        prod_value = configs.get(prod_env, {}).get(key)
        for env, val in values.items():
            if env != prod_env and prod_value is not None and val != prod_value:
                prod_diffs.setdefault(key, {})[env] = {
                    "expected": prod_value,
                    "actual": val,
                }

    # Remove entries for environments with no missing keys
    missing_keys = {env: sorted(keys) for env, keys in missing_keys.items() if keys}

    return {
        "missing_keys": missing_keys,
        "value_diffs": value_diffs,
        "prod_diffs": prod_diffs,
    }
