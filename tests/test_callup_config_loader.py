from pathlib import Path

from src.callup_config import DEFAULT_CALLOUP_CONFIG, load_callup_config


def test_min_b_starters_default_and_override(tmp_path):
    cfg_missing, _ = load_callup_config(path=tmp_path / "missing.yml")
    assert cfg_missing.min_b_starters == DEFAULT_CALLOUP_CONFIG.min_b_starters

    cfg_path = tmp_path / "custom.yml"
    cfg_path.write_text(
        "\n".join(
            [
                "version: 2",
                "min_events: 2",
                "low_n_max_events: 1",
                "callup_min_attend_prob: 0.7",
                "min_b_starters: 5",
            ]
        ),
        encoding="utf-8",
    )

    cfg_loaded, meta = load_callup_config(path=cfg_path)
    assert cfg_loaded.min_b_starters == 5
    assert meta.get("loaded_from_file") is True
