"""
Load and save keyswitch mapping presets as JSON files.
"""
import json
import os
from pathlib import Path
from .technique_mapper import KeyswitchMapping

BUILTIN_PRESETS_DIR = Path(__file__).parent.parent / "presets"
USER_PRESETS_DIR = Path.home() / "Library" / "Application Support" / "GP2Logic" / "presets"


def ensure_user_presets_dir():
    USER_PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def list_presets() -> list[dict]:
    """Return [{name, path, builtin}] for all available presets."""
    presets = []
    for d, builtin in [(BUILTIN_PRESETS_DIR, True), (USER_PRESETS_DIR, False)]:
        if d.exists():
            for f in sorted(d.glob("*.json")):
                presets.append({"name": f.stem, "path": str(f), "builtin": builtin})
    return presets


def load_preset(path: str) -> tuple[str, KeyswitchMapping]:
    """Load a preset JSON and return (name, KeyswitchMapping)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("name", Path(path).stem)
    mapping = KeyswitchMapping.from_dict(data)
    return name, mapping


def save_preset(name: str, mapping: KeyswitchMapping, path: str = None) -> str:
    """Save mapping to JSON. Returns the saved path."""
    ensure_user_presets_dir()
    if path is None:
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
        path = str(USER_PRESETS_DIR / f"{safe_name}.json")
    data = mapping.to_dict()
    data["name"] = name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def delete_preset(path: str):
    """Delete a user preset file."""
    p = Path(path)
    if not str(p).startswith(str(USER_PRESETS_DIR)):
        raise PermissionError("Cannot delete built-in presets.")
    p.unlink(missing_ok=True)
