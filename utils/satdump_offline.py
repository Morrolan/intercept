"""Per-run SatDump 1.2.2 settings for historical Meteor image decoding.

Orbital projection and scripted composites can crash on short/old recordings.
Keep image-based composites, without altering settings used by live capture.
"""

import json
import re
import shutil
from pathlib import Path

_COMMENTS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
_OVERLAYS = (
    "draw_map_overlay", "draw_cities_overlay", "draw_qth_overlay",
    "draw_latlon_overlay", "draw_shores_overlay",
)


def offline_settings(config: dict) -> dict:
    """Build a SatDump user-settings diff, retaining the master's image recipes."""
    instruments = config.get("viewer", {}).get("instruments")
    if not isinstance(instruments, dict):
        raise ValueError("SatDump configuration is missing image-processing settings")
    overrides = {}
    for name, instrument in instruments.items():
        settings = {}
        # SatDump deletes existing keys for null, but ADDS null for absent keys.
        if "project_channels" in instrument:
            settings["project_channels"] = None
        recipes = {}
        for title, recipe in instrument.get("rgb_composites", {}).items():
            override = dict.fromkeys(_OVERLAYS, False)
            if "project" in recipe:
                override["project"] = None
            # Scripted compositors/background removal may request orbital geometry.
            if recipe.get("lua") or recipe.get("cpp") or recipe.get("remove_background"):
                override["autogen"] = False
            recipes[title] = override
        settings["rgb_composites"] = recipes
        overrides[name] = settings
    return {"viewer": {"instruments": overrides}}


def prepare_offline_run(directory: Path) -> Path:
    """Write settings in the child's own cwd and return its empty TLE override."""
    executable = shutil.which("satdump")
    if not executable:
        raise ValueError("SatDump is not installed")
    candidates = (
        Path(executable).resolve().parent.parent / "share/satdump/satdump_cfg.json",
        Path("/usr/local/share/satdump/satdump_cfg.json"),
        Path("/usr/share/satdump/satdump_cfg.json"),
    )
    master = next((path for path in candidates if path.is_file()), None)
    if master is None:
        raise ValueError("SatDump configuration not found; check its installed resources")
    text = master.read_text(encoding="utf-8-sig")
    # Preserve quoted strings (including URLs/escapes) while removing JSON comments.
    config = json.loads(_COMMENTS.sub(lambda match: match.group(1) or "", text))
    (directory / "settings.json").write_text(json.dumps(offline_settings(config)), encoding="utf-8")
    tle = directory / "offline.tle"
    tle.write_text("", encoding="utf-8")
    return tle
