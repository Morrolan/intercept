"""Offline processing must not require present-day orbital data for old files."""

import copy
import json


def test_profile_removes_only_existing_orbital_keys_and_preserves_composites():
    from utils.satdump_offline import offline_settings

    config = {"viewer": {"instruments": {"msu_mr": {
        "project_channels": {"channels": "all"},
        "rgb_composites": {
            "RGB": {"equation": "ch1,ch2,ch3", "project": {"config": {}}},
            "LUT": {"lut": "colours.png"},
            "Day/night": {"cpp": "orbital_compositor"},
            "Scripted": {"lua": "orbital.lua"},
            "Background": {"remove_background": True},
            "Manual": {"equation": "ch1", "autogen": False},
        },
    }}}}
    before = copy.deepcopy(config)
    result = offline_settings(config)["viewer"]["instruments"]["msu_mr"]
    assert config == before  # Live/master configuration remains unchanged.
    assert result["project_channels"] is None
    recipes = result["rgb_composites"]
    assert recipes["RGB"]["project"] is None
    assert "project" not in recipes["LUT"]  # Null on an absent key would ADD it in SatDump.
    assert "autogen" not in recipes["RGB"]
    assert "autogen" not in recipes["LUT"]
    assert "autogen" not in recipes["Manual"]  # Preserve an existing manual-only recipe.
    for name in ["Day/night", "Scripted", "Background"]:
        assert recipes[name]["autogen"] is False
    assert recipes["RGB"]["draw_map_overlay"] is False
    assert recipes["RGB"]["draw_cities_overlay"] is False
    assert recipes["RGB"]["draw_qth_overlay"] is False
    assert recipes["RGB"]["draw_latlon_overlay"] is False
    assert recipes["RGB"]["draw_shores_overlay"] is False


def test_profile_does_not_add_null_projection_fields_to_unprojected_instrument():
    from utils.satdump_offline import offline_settings

    result = offline_settings({"viewer": {"instruments": {"mtvza": {}}}})
    assert "project_channels" not in result["viewer"]["instruments"]["mtvza"]


def test_preparation_reads_commented_master_without_changing_it(tmp_path, monkeypatch):
    from utils.satdump_offline import prepare_offline_run

    install = tmp_path / "install"
    config = install / "share" / "satdump" / "satdump_cfg.json"
    config.parent.mkdir(parents=True)
    text = '''{
        // SatDump ships JSON with comments.
        "viewer": {"instruments": {"msu_mr": {"rgb_composites": {
            "http://example.test/image": {"equation": "ch1"} /* a block comment */
        }}}}
    }'''
    config.write_text(text)
    monkeypatch.setattr("shutil.which", lambda _: str(install / "bin" / "satdump"))
    folder = tmp_path / "run"
    folder.mkdir()
    tle = prepare_offline_run(folder)
    assert tle == folder / "offline.tle"
    assert tle.read_bytes() == b""
    generated = json.loads((folder / "settings.json").read_text())
    assert "http://example.test/image" in generated["viewer"]["instruments"]["msu_mr"]["rgb_composites"]
    assert config.read_text() == text
