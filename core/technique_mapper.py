"""
Maps GuitarPro technique flags to a named articulation key,
which the user then maps to a MIDI keyswitch note.

Articulation IDs follow GuitarPro's own technique vocabulary so the
left column of the keyswitch editor shows familiar GP technique names.
"""
from dataclasses import dataclass, field
from typing import ClassVar, Optional

# Canonical articulation IDs — aligned with GuitarPro's technique names.
# Order here controls the display order in the keyswitch editor.
ARTICULATION_IDS = [
    # ── ピッキング ──────────────────────────────────────────────────────────
    "normal",              # 通常
    "accent",              # アクセント
    "strong_accent",       # 強アクセント（マルカート）
    "ghost_note",          # ゴーストノート
    "dead_note",           # デッドノート
    # ── レガート ────────────────────────────────────────────────────────────
    "hammer_on",           # ハンマリング
    "pull_off",            # プリング
    # ── スライド ────────────────────────────────────────────────────────────
    "shift_slide",         # シフトスライド
    "legato_slide",        # レガートスライド
    "slide_out_down",      # スライドアウト（下）
    "slide_out_up",        # スライドアウト（上）
    "slide_in_below",      # スライドイン（下から）
    "slide_in_above",      # スライドイン（上から）
    # ── パームミュート ──────────────────────────────────────────────────────
    "palm_mute",           # パームミュート
    "palm_mute_dead",      # パームミュート＋デッドノート
    # ── ハーモニクス ────────────────────────────────────────────────────────
    "natural_harmonic",    # ナチュラルハーモニクス
    "pinch_harmonic",      # ピンチハーモニクス
    "artificial_harmonic", # アーティフィシャルハーモニクス
    # ── 特殊奏法 ────────────────────────────────────────────────────────────
    "tremolo_picking",     # トレモロピッキング
    "tapping",             # タッピング
    "slap",                # スラップ
    "pop",                 # ポップ
]

# Display labels shown in the keyswitch editor left column.
ARTICULATION_LABELS = {
    "normal":              "通常",
    "accent":              "アクセント",
    "strong_accent":       "強アクセント（マルカート）",
    "ghost_note":          "ゴーストノート",
    "dead_note":           "デッドノート",
    "hammer_on":           "ハンマリング",
    "pull_off":            "プリング",
    "shift_slide":         "シフトスライド",
    "legato_slide":        "レガートスライド",
    "slide_out_down":      "スライドアウト（下）",
    "slide_out_up":        "スライドアウト（上）",
    "slide_in_below":      "スライドイン（下から）",
    "slide_in_above":      "スライドイン（上から）",
    "palm_mute":           "パームミュート",
    "palm_mute_dead":      "パームミュート＋デッドノート",
    "natural_harmonic":    "ナチュラルハーモニクス",
    "pinch_harmonic":      "ピンチハーモニクス",
    "artificial_harmonic": "アーティフィシャルハーモニクス",
    "tremolo_picking":     "トレモロピッキング",
    "tapping":             "タッピング",
    "slap":                "スラップ",
    "pop":                 "ポップ",
}

# Map from old (pre-GP-vocab) articulation IDs → new IDs.
# Used in KeyswitchMapping.from_dict() to migrate saved presets automatically.
_LEGACY_ID_MAP: dict = {
    "alternate_picked":           "normal",
    "down_picked":                "normal",
    "up_picked":                  "normal",
    "palm_mute_alt":              "palm_mute",
    "palm_mute_down":             "palm_mute",
    "palm_mute_up":               "palm_mute",
    "palm_mute_semi_closed_alt":  None,   # no GP-vocab equivalent
    "palm_mute_semi_closed_down": None,
    "palm_mute_semi_closed_up":   None,
    "palm_mute_closed_alt":       None,
    "palm_mute_closed_down":      None,
    "palm_mute_closed_up":        None,
    "palm_mute_dead_alt":         "palm_mute_dead",
    "palm_mute_dead_down":        "palm_mute_dead",
    "palm_mute_dead_up":          "palm_mute_dead",
    "slide_auto":                 "shift_slide",
    "slide_slow_from_up":         "slide_in_above",
    "slide_slow_from_down":       "slide_in_below",
    "slide_slow_to_down":         "slide_out_down",
    "slide_slow_to_up":           "slide_out_up",
    "slide_fast_from_up":         "slide_in_above",
    "slide_fast_from_down":       "slide_in_below",
    "slide_fast_to_down":         "slide_out_down",
    "slide_fast_to_up":           "slide_out_up",
    "bend_up_fast":               None,   # pitch bend で処理（キースイッチ不要）
    "bend_up_slow":               None,
    "tremolo_picked":             "tremolo_picking",
    "nasty_pinch_harmonic":       "pinch_harmonic",
    "thumb_slap":                 "slap",
    "scrapes_noises":             None,
    "auto_power_chord":           None,
    "finger_pluck_open":          None,
    "finger_pluck_dead":          None,
}


@dataclass
class KeyswitchMapping:
    """Maps articulation IDs to MIDI keyswitch note numbers.

    Articulation is determined entirely from GPIF technique detection
    (note/beat/bar level).  Velocity only affects note loudness.
    """
    note_map: dict = field(default_factory=dict)   # articulation_id -> midi_note (int)
    default_articulation: str = ""  # keyswitch sent at MIDI start to initialize sampler

    # Fallback chain: if an articulation has no assigned keyswitch, try these in order.
    # palm_mute_dead → palm_mute (use the regular PM sample when no dead-PM KS is set)
    _PM_FALLBACKS: ClassVar[dict] = {
        "palm_mute_dead": ("palm_mute",),
    }

    def get_note(self, articulation_id: str) -> Optional[int]:
        note = self.note_map.get(articulation_id)
        if note is not None:
            return note
        # PM family automatic fallback: unspecified/up stroke → try related variants
        for fallback in self._PM_FALLBACKS.get(articulation_id, ()):
            note = self.note_map.get(fallback)
            if note is not None:
                return note
        return None

    def set_note(self, articulation_id: str, midi_note: Optional[int]):
        self.note_map[articulation_id] = midi_note

    def to_dict(self) -> dict:
        d: dict = {"note_map": {k: v for k, v in self.note_map.items() if v is not None}}
        if self.default_articulation:
            d["default_articulation"] = self.default_articulation
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "KeyswitchMapping":
        mapping = cls()
        raw_map = {k: int(v) for k, v in data.get("note_map", {}).items()}

        # Migrate legacy articulation IDs → GP-vocab IDs.
        # When multiple old IDs map to the same new ID, the first encountered wins.
        migrated: dict = {}
        for old_id, midi_note in raw_map.items():
            new_id = _LEGACY_ID_MAP.get(old_id, old_id)   # unknown old IDs pass through
            if new_id is None:
                continue   # dropped (Odin3-only, no GP-vocab equivalent)
            if new_id not in migrated:
                migrated[new_id] = midi_note

        mapping.note_map = migrated

        # Migrate default_articulation field
        raw_default = data.get("default_articulation", "")
        mapping.default_articulation = _LEGACY_ID_MAP.get(raw_default, raw_default) or ""

        # velocity_triggers field is ignored (removed feature) — silently skipped
        return mapping


def midi_note_to_name(note: int) -> str:
    """Convert MIDI note number to name using Logic Pro convention (C3=60)."""
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = (note // 12) - 2   # Logic: C3=60 → octave offset = -2 from standard
    name = names[note % 12]
    return f"{name}{octave}"


def note_name_to_midi(name: str) -> Optional[int]:
    """Convert note name like 'C-2' or 'C#0' to MIDI number."""
    name = name.strip()
    note_names = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3,
                  "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
                  "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
    for n, semitone in sorted(note_names.items(), key=lambda x: -len(x[0])):
        if name.upper().startswith(n):
            octave_str = name[len(n):]
            try:
                octave = int(octave_str)
                return (octave + 2) * 12 + semitone
            except ValueError:
                return None
    return None
