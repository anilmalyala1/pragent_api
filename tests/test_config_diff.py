from app.utils.config_diff import diff_configs


def test_diff_configs_identifies_deltas():
    configs = {
        "prod": {"a": 1, "b": 2},
        "dev": {"a": 1, "c": 3},
        "stage": {"a": 1, "b": 4},
    }

    diff = diff_configs(configs, prod_env="prod")

    assert diff["missing_keys"] == {
        "prod": ["c"],
        "dev": ["b"],
        "stage": ["c"],
    }
    assert diff["value_diffs"] == {"b": {"prod": 2, "stage": 4}}
    assert diff["prod_diffs"] == {
        "b": {"stage": {"expected": 2, "actual": 4}}
    }
