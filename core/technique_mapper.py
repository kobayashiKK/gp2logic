"""
Maps GuitarPro technique flags to a named articulation key,
which the user then maps to a MIDI keyswitch note.
"""
from dataclasses import dataclass, field
from typing import Optional

# Canonical articulation IDs used throughout the app
ARTICULATION_IDS = [
    "alternate_picked",
    "down_picked",
    "up_picked",
    "palm_mute_down",
    "palm_mute_up",
    "palm_mute_alt",
    "palm_mute_semi_closed_down",
    "palm_mute_semi_closed_up",
    "palm_mute_semi_closed_alt",
    "palm_mute_closed_down",
    "palm_mute_closed_up",
    "palm_mute_closed_alt",
    "palm_mute_dead_down",
    "palm_mute_dead_up",
    "palm_mute_dead_alt",
    "hammer_on",
    "pull_off",
    "natural_harmonic",
    "pinch_harmonic",
    "nasty_pinch_harmonic",
    "artificial_harmonic",
    "slide_auto",
    "slide_slow_from_up",
    "slide_slow_from_down",
    "slide_slow_to_down",
    "slide_slow_to_up",
    "slide_fast_from_up",
    "slide_fast_from_down",
    "slide_fast_to_down",
    "slide_fast_to_up",
    "tremolo_picked",
    "vibrato",
    "bend_up_fast",
    "bend_up_slow",
    "tapping",
    "slap",
    "pop",
    "dead_note",
    "scrapes_noises",
    "auto_power_chord",
    "finger_pluck_open",
    "finger_pluck_dead",
    "thumb_slap",
]

ARTICULATION_LABELS = {
    "alternate_picked":           "Alternate Picked",
    "down_picked":                "Down Picked",
    "up_picked":                  "Up Picked",
    "palm_mute_down":             "Down Open Palm Mute",
    "palm_mute_up":               "Up Open Palm Mute",
    "palm_mute_alt":              "Alt Open Palm Mute",
    "palm_mute_semi_closed_down": "Down Mute Semi Closed",
    "palm_mute_semi_closed_up":   "Up Mute Semi Closed",
    "palm_mute_semi_closed_alt":  "Alternate Mute Semi Closed",
    "palm_mute_closed_down":      "Down Mute Closed",
    "palm_mute_closed_up":        "Up Mute Closed",
    "palm_mute_closed_alt":       "Alternate Mute Closed",
    "palm_mute_dead_down":        "Down Mute Dead",
    "palm_mute_dead_up":          "Up Mute Dead",
    "palm_mute_dead_alt":         "Alternate Mute Dead",
    "hammer_on":                  "Hammer-On",
    "pull_off":                   "Pull-Off",
    "natural_harmonic":           "Natural Harmonic",
    "pinch_harmonic":             "Pinch Harmonic",
    "nasty_pinch_harmonic":       "Nasty Pinch Harmonic",
    "artificial_harmonic":        "Artificial Harmonic",
    "slide_auto":                 "*Auto Slide",
    "slide_slow_from_up":         "Slide Slow From Up",
    "slide_slow_from_down":       "Slide Slow From Down",
    "slide_slow_to_down":         "Slide Slow To Down",
    "slide_slow_to_up":           "Slide Slow To Up",
    "slide_fast_from_up":         "Slide Fast From Up",
    "slide_fast_from_down":       "Slide Fast From Down",
    "slide_fast_to_down":         "Slide Fast To Down",
    "slide_fast_to_up":           "Slide Fast To Up",
    "tremolo_picked":             "Tremolo Picked",
    "vibrato":                    "Vibrato",
    "bend_up_fast":               "Bend Up Fast",
    "bend_up_slow":               "Bend Up Slow",
    "tapping":                    "Tapping",
    "slap":                       "Slap",
    "pop":                        "Pop",
    "dead_note":                  "Dead Note",
    "scrapes_noises":             "Scrapes & Noises",
    "auto_power_chord":           "*Auto Power Chord",
    "finger_pluck_open":          "Finger Pluck Open",
    "finger_pluck_dead":          "Finger Pluck Dead",
    "thumb_slap":                 "Thumb Slap",
}


@dataclass
class VelocityTrigger:
    min_vel: int
    max_vel: int
    articulation_id: str


@dataclass
class KeyswitchMapping:
    """Maps articulation IDs to MIDI note numbers and optional velocity triggers."""
    note_map: dict = field(default_factory=dict)        # articulation_id -> midi_note (int or None)
    velocity_triggers: list = field(default_factory=list)  # list of VelocityTrigger
    default_articulation: str = ""  # keyswitch inserted at MIDI start (empty = none)

    def get_note(self, articulation_id: str) -> Optional[int]:
        return self.note_map.get(articulation_id)

    def set_note(self, articulation_id: str, midi_note: Optional[int]):
        self.note_map[articulation_id] = midi_note

    def to_dict(self) -> dict:
        d = {
            "note_map": {k: v for k, v in self.note_map.items() if v is not None},
            "velocity_triggers": [
                {"min": vt.min_vel, "max": vt.max_vel, "articulation": vt.articulation_id}
                for vt in self.velocity_triggers
            ],
        }
        if self.default_articulation:
            d["default_articulation"] = self.default_articulation
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "KeyswitchMapping":
        mapping = cls()
        mapping.note_map = {k: int(v) for k, v in data.get("note_map", {}).items()}
        mapping.velocity_triggers = [
            VelocityTrigger(vt["min"], vt["max"], vt["articulation"])
            for vt in data.get("velocity_triggers", [])
        ]
        mapping.default_articulation = data.get("default_articulation", "")
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
