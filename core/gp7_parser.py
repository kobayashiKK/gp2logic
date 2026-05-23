"""
Parser for Guitar Pro 7+ (.gp) files.
These are ZIP archives containing Content/score.gpif (GPIF XML format).
"""
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


# GPIF NoteValue string → ticks at 960 ticks/quarter
_NOTE_VALUE_TICKS = {
    "Whole":    3840,
    "Half":     1920,
    "Quarter":  960,
    "Eighth":   480,
    "16th":     240,
    "32nd":     120,
    "64th":     60,
}

# Dynamic → MIDI velocity
_DYNAMIC_VEL = {
    "PPP": 15, "PP": 30, "P": 45, "MP": 60,
    "MF": 75,  "F": 90,  "FF": 105, "FFF": 120,
}


# ── XML helpers ──────────────────────────────────────────────────────────────

def _prop(element, name: str) -> Optional[ET.Element]:
    if element is None:
        return None
    for p in element.findall("Properties/Property"):
        if p.get("name") == name:
            return p
    return None


def _prop_text(element, name: str, child_tag: str) -> Optional[str]:
    p = _prop(element, name)
    if p is None:
        return None
    c = p.find(child_tag)
    return c.text.strip() if c is not None and c.text else None


def _prop_enabled(element, name: str) -> bool:
    """True if Property[@name] has <Enable/> or <Enable>true</Enable>."""
    p = _prop(element, name)
    if p is None:
        return False
    e = p.find("Enable")
    if e is None:
        return False
    if not e.text or e.text.strip() == "":
        return True   # <Enable /> means enabled
    return e.text.strip().lower() in ("true", "1")


# ── Rhythm ───────────────────────────────────────────────────────────────────

def _parse_rhythms(root: ET.Element) -> dict:
    rhythms = {}
    for r in root.findall("Rhythms/Rhythm"):
        rid = r.get("id")
        nv_el = r.find("NoteValue")
        nv = nv_el.text.strip() if nv_el is not None and nv_el.text else "Quarter"
        base = _NOTE_VALUE_TICKS.get(nv, 960)

        # AugmentationDot uses attribute "count" (not child element Count)
        dot_el = r.find("AugmentationDot")
        dots = 0
        if dot_el is not None:
            count_attr = dot_el.get("count")
            if count_attr:
                dots = int(count_attr)
            else:
                count_child = dot_el.find("Count")
                if count_child is not None and count_child.text:
                    dots = int(count_child.text)

        # PrimaryTuplet uses attributes "num"/"den" (not child elements Num/Den)
        tup = r.find("PrimaryTuplet")
        t_num, t_den = 1, 1
        if tup is not None:
            num_attr = tup.get("num")
            den_attr = tup.get("den")
            if num_attr and den_attr:
                t_num, t_den = int(num_attr), int(den_attr)
            else:
                n = tup.find("Num")
                d = tup.find("Den")
                if n is not None and n.text: t_num = int(n.text)
                if d is not None and d.text: t_den = int(d.text)

        ticks = base
        if dots == 1:   ticks = ticks * 3 // 2
        elif dots == 2:  ticks = ticks * 7 // 4
        if t_num != t_den and t_den:
            ticks = ticks * t_den // t_num

        rhythms[rid] = max(1, ticks)
    return rhythms


# ── Voices (top-level section) ───────────────────────────────────────────────

def _parse_voices_section(root: ET.Element) -> dict:
    """voice_id → [beat_id, ...] (already filtered for -1)"""
    voices = {}
    for v in root.findall("Voices/Voice"):
        vid = v.get("id")
        beats_el = v.find("Beats")
        if beats_el is not None and beats_el.text:
            voices[vid] = [b for b in beats_el.text.split() if b != "-1"]
        else:
            voices[vid] = []
    return voices


# ── Bars ─────────────────────────────────────────────────────────────────────

@dataclass
class _BarInfo:
    voices: list          # [[beat_ids per voice]]
    is_palm_mute: bool    # bar-level palm mute (persists to all beats in bar)
    stroke: Optional[str] # bar-level stroke direction (may override beat stroke)


def _parse_bars(root: ET.Element, voices_map: dict) -> dict:
    """bar_id → _BarInfo"""
    bars = {}
    for b in root.findall("Bars/Bar"):
        bid = b.get("id")

        # Bar-level palm mute: GP can mark a whole bar as PM via drag gesture.
        # This is stored on the Bar element rather than individual Beat elements,
        # because the same Beat ID may be reused across PM and non-PM bars.
        bar_pm     = _prop_enabled(b, "PalmMute")
        bar_stroke = _prop_text(b, "Stroke", "Direction")

        voices_el = b.find("Voices")
        if voices_el is None or not voices_el.text:
            bars[bid] = _BarInfo(voices=[], is_palm_mute=bar_pm, stroke=bar_stroke)
            continue
        voice_ids = voices_el.text.split()
        bar_voices = []
        for vid in voice_ids:
            if vid == "-1":
                continue
            beat_ids = voices_map.get(vid, [])
            if beat_ids:
                bar_voices.append(beat_ids)
        bars[bid] = _BarInfo(voices=bar_voices, is_palm_mute=bar_pm, stroke=bar_stroke)
    return bars


# ── Beats ─────────────────────────────────────────────────────────────────────

@dataclass
class _BeatInfo:
    note_ids: list
    rhythm_ticks: int
    stroke: Optional[str]
    is_palm_mute: bool
    is_tremolo: bool
    is_slap: bool
    is_pop: bool
    is_tapped: bool
    velocity: int


def _parse_beats(root: ET.Element, rhythms: dict) -> dict:
    beats = {}
    for b in root.findall("Beats/Beat"):
        bid = b.get("id")

        notes_el = b.find("Notes")
        note_ids = notes_el.text.split() if notes_el is not None and notes_el.text else []

        rhythm_el = b.find("Rhythm")
        rid = rhythm_el.get("ref") if rhythm_el is not None else None
        dur = rhythms.get(rid, 960)

        # Beat properties
        stroke_dir = _prop_text(b, "Stroke", "Direction")
        is_pm      = _prop_enabled(b, "PalmMute")
        is_tremolo = (_prop_enabled(b, "Tremolo") or
                      _prop_enabled(b, "TremoloPicking") or
                      _prop_enabled(b, "TremoloSpeed"))
        is_slap    = _prop_enabled(b, "Slapped")
        is_pop     = _prop_enabled(b, "Popped")
        is_tapped  = _prop_enabled(b, "Tapped")

        dyn_el = b.find("Dynamic")
        dyn = dyn_el.text.strip() if dyn_el is not None and dyn_el.text else None
        vel = _DYNAMIC_VEL.get(dyn, 95) if dyn else 95

        beats[bid] = _BeatInfo(
            note_ids=note_ids,
            rhythm_ticks=dur,
            stroke=stroke_dir,
            is_palm_mute=is_pm,
            is_tremolo=is_tremolo,
            is_slap=is_slap,
            is_pop=is_pop,
            is_tapped=is_tapped,
            velocity=vel,
        )
    return beats


# ── Notes ─────────────────────────────────────────────────────────────────────

@dataclass
class _NoteInfo:
    midi_pitch: int
    string: int           # 0-based (GPIF convention)
    fret: int
    is_tie_dest: bool
    is_tie_origin: bool
    articulation_id: str
    is_dead: bool
    is_palm_mute: bool    # Note-level palm mute (<Property name="PalmMuted"><Enable /></Property>)
    is_hopo: bool
    slide_flags: int
    has_bend: bool
    has_vibrato: bool
    harmonic_type: Optional[str]
    bend_points: list = field(default_factory=list)  # list of (offset_frac, semitones)


def _parse_bend_points(n: ET.Element) -> list:
    """
    Parse GPIF bend envelope into [(offset_frac, semitones), ...].
    GPIF stores offsets as 0-100 percentages, values in quarter-tone units
    where 25 = 1 quarter-tone, 50 = 1 semitone, 100 = 1 whole tone (2 semitones).
    We convert: semitones = value / 50.0
    """
    def _float(name):
        v = _prop_text(n, name, "Float")
        return float(v) if v is not None else None

    from .gp_parser import BendPoint
    points = []

    origin_off = _float("BendOriginOffset")
    origin_val = _float("BendOriginValue")
    if origin_off is not None and origin_val is not None:
        points.append(BendPoint(origin_off / 100.0, origin_val / 50.0))

    for i in ("1", "2"):
        mid_off = _float(f"BendMiddleOffset{i}")
        mid_val = _float("BendMiddleValue") if i == "1" else None
        if mid_off is not None and mid_val is not None:
            points.append(BendPoint(mid_off / 100.0, mid_val / 50.0))

    dest_off = _float("BendDestinationOffset")
    dest_val = _float("BendDestinationValue")
    if dest_off is not None and dest_val is not None:
        points.append(BendPoint(dest_off / 100.0, dest_val / 50.0))

    # Sort by offset and ensure we start from 0
    points.sort(key=lambda p: p.offset_frac)
    if not points or points[0].offset_frac > 0.0:
        points.insert(0, BendPoint(0.0, 0.0))

    return points


def _parse_notes(root: ET.Element) -> dict:
    notes = {}
    for n in root.findall("Notes/Note"):
        nid = n.get("id")

        tie_el = n.find("Tie")
        is_tie_dest   = (tie_el is not None and
                         tie_el.get("destination", "false").lower() == "true")
        is_tie_origin = (tie_el is not None and
                         tie_el.get("origin", "false").lower() == "true")

        # MIDI pitch: use Midi property directly (most reliable)
        midi_num = _prop_text(n, "Midi", "Number")
        midi_pitch = int(midi_num) if midi_num is not None else 60

        # String (0-based in GPIF: 0=lowest string)
        str_text = _prop_text(n, "String", "String")
        string = int(str_text) if str_text is not None else 0

        # Fret
        fret_text = _prop_text(n, "Fret", "Fret")
        fret = int(fret_text) if fret_text is not None else 0

        # Harmonic
        h_type = _prop_text(n, "HarmonicType", "HType")

        # Slide flags (bitmask)
        slide_flags = 0
        sp = _prop(n, "Slide")
        if sp is not None:
            f_el = sp.find("Flags")
            if f_el is not None and f_el.text:
                try:
                    slide_flags = int(f_el.text)
                except ValueError:
                    pass

        # Vibrato
        has_vibrato = (_prop_enabled(n, "Vibrato") or
                       _prop_enabled(n, "VibratoWTremBar"))

        # Bend
        has_bend = (_prop_enabled(n, "Bended") or
                    _prop_enabled(n, "BendedStrong") or
                    _prop(n, "Bend") is not None)

        # HopoDestination = この音がハンマリング/プリングで鳴る音
        # HopoOrigin は「次の音がH/P」という意味なので起点音自体は普通に弾く
        is_hopo = _prop_enabled(n, "HopoDestination")

        # Palm mute: stored at note level as "PalmMuted" (with 'd'), NOT at beat level
        # GuitarPro's drag-PM gesture marks each note individually.
        is_palm_mute = _prop_enabled(n, "PalmMuted")

        # Dead / muted note
        is_dead = _prop_enabled(n, "Muted") or _prop_enabled(n, "DeadNote")
        nt = n.find("NoteType")
        if nt is not None and nt.text and nt.text.strip().lower() in ("dead", "muted"):
            is_dead = True

        # Determine articulation (beat-level may override this later)
        art = "alternate_picked"
        if h_type == "Natural":
            art = "natural_harmonic"
        elif h_type in ("Pinch", "Semi"):
            art = "pinch_harmonic"
        elif h_type in ("Artificial", "Tapped", "Feedback"):
            art = "artificial_harmonic"
        elif is_hopo:
            art = "hammer_on"
        elif slide_flags:
            art = "slide_auto"
        elif has_bend:
            art = "bend_up_slow"
        elif has_vibrato:
            art = "vibrato"
        elif is_dead:
            art = "dead_note"

        bend_points = _parse_bend_points(n) if has_bend else []

        notes[nid] = _NoteInfo(
            midi_pitch=midi_pitch,
            string=string,
            fret=fret,
            is_tie_dest=is_tie_dest,
            is_tie_origin=is_tie_origin,
            articulation_id=art,
            is_dead=is_dead,
            is_palm_mute=is_palm_mute,
            is_hopo=is_hopo,
            slide_flags=slide_flags,
            has_bend=has_bend,
            has_vibrato=has_vibrato,
            harmonic_type=h_type,
            bend_points=bend_points,
        )
    return notes


# ── Tracks ────────────────────────────────────────────────────────────────────

def _parse_tracks(root: ET.Element) -> list:
    result = []
    for t in root.findall("Tracks/Track"):
        tid = t.get("id")
        name_el = t.find("Name")
        name = name_el.text.strip() if name_el is not None and name_el.text else f"Track {tid}"

        ch_el = t.find("MidiConnection/PrimaryChannel")
        if ch_el is None:
            ch_el = t.find("Channel")
        channel = int(ch_el.text) if ch_el is not None and ch_el.text else 0

        result.append({"id": tid, "name": name, "channel": channel})
    return result


def _parse_masterbars(root: ET.Element) -> list:
    """Returns list of (bar_ids, bar_ticks) per MasterBar."""
    result = []
    for mb in root.findall("MasterBars/MasterBar"):
        bars_el = mb.find("Bars")
        bar_ids = bars_el.text.split() if bars_el is not None and bars_el.text else []

        time_el = mb.find("Time")
        bar_ticks = 3840  # default 4/4 at 960 tpb
        if time_el is not None and time_el.text:
            try:
                num, den = map(int, time_el.text.strip().split("/"))
                bar_ticks = num * 3840 // den
            except (ValueError, ZeroDivisionError):
                pass

        result.append((bar_ids, bar_ticks))
    return result


def _tempo_from_root(root: ET.Element) -> float:
    for auto in root.findall("MasterTrack/Automations/Automation"):
        t_el = auto.find("Type")
        if t_el is not None and t_el.text and t_el.text.strip() == "Tempo":
            val_el = auto.find("Value")
            if val_el is not None and val_el.text:
                try:
                    return float(val_el.text.strip().split()[0])
                except (ValueError, IndexError):
                    pass
    return 120.0


# ── Articulation resolution ───────────────────────────────────────────────────

def _resolve_art(note: _NoteInfo, beat: _BeatInfo,
                 bar_palm_mute: bool = False,
                 bar_stroke: Optional[str] = None) -> str:
    """Apply beat-level (and bar-level) technique flags on top of note-level articulation.

    bar_palm_mute: True when the containing Bar element has PalmMute enabled.
                   Guitar Pro stores "drag" palm-mute sections at Bar level rather
                   than per-Beat, because the same Beat ID is shared across bars.
    bar_stroke:    Stroke direction from the Bar element (overrides beat stroke when set).
    """
    if beat.is_slap:    return "slap"
    if beat.is_pop:     return "pop"
    if beat.is_tapped:  return "tapping"

    art = note.articulation_id

    # Tremolo only overrides the default
    if beat.is_tremolo and art == "alternate_picked":
        return "tremolo_picked"

    # Note-level articulations that beat stroke/PM should NOT override
    if art in ("natural_harmonic", "pinch_harmonic", "artificial_harmonic",
               "hammer_on", "pull_off", "slide_auto",
               "bend_up_slow", "vibrato", "dead_note"):
        return art

    # Merge PM flags: note-level (PalmMuted property) is the primary source.
    # Beat-level and bar-level are kept as fallbacks for any edge-case GP variants.
    is_pm  = note.is_palm_mute or beat.is_palm_mute or bar_palm_mute
    stroke = beat.stroke if beat.stroke else bar_stroke

    if is_pm:
        if note.is_dead:  return _pm_dead(stroke)
        else:              return _pm(stroke)
    else:
        if note.is_dead:  return "dead_note"
        else:              return _stroke(stroke)


def _stroke(d: Optional[str]) -> str:
    if d is None: return "alternate_picked"
    d = d.lower()
    if "down" in d: return "down_picked"
    if "up"   in d: return "up_picked"
    return "alternate_picked"


def _pm(d: Optional[str]) -> str:
    if d is None: return "palm_mute_alt"
    d = d.lower()
    if "down" in d: return "palm_mute_down"
    if "up"   in d: return "palm_mute_up"
    return "palm_mute_alt"


def _pm_dead(d: Optional[str]) -> str:
    if d is None: return "palm_mute_dead_alt"
    d = d.lower()
    if "down" in d: return "palm_mute_dead_down"
    if "up"   in d: return "palm_mute_dead_up"
    return "palm_mute_dead_alt"


# ── Main entry point ──────────────────────────────────────────────────────────

from .gp_parser import TrackInfo, NoteEvent, BendPoint


def parse_gp7_file(filepath: str) -> tuple:
    """
    Parse a Guitar Pro 7 .gp file (ZIP + GPIF XML).
    Returns (tempo_bpm, [TrackInfo]).
    """
    with zipfile.ZipFile(filepath, "r") as zf:
        names = zf.namelist()
        gpif_path = None
        for candidate in ("Content/score.gpif", "score.gpif", "content/score.gpif"):
            if candidate in names:
                gpif_path = candidate
                break
        if gpif_path is None:
            for n in names:
                if n.lower().endswith("score.gpif"):
                    gpif_path = n
                    break
        if gpif_path is None:
            raise ValueError(
                f"score.gpif が見つかりません。ZIP内容: {names[:15]}"
            )
        xml_data = zf.read(gpif_path)

    root = ET.fromstring(xml_data)

    tempo      = _tempo_from_root(root)
    rhythms    = _parse_rhythms(root)
    voices_map = _parse_voices_section(root)
    bars_map   = _parse_bars(root, voices_map)
    beats_map  = _parse_beats(root, rhythms)
    notes_map  = _parse_notes(root)
    tracks_raw = _parse_tracks(root)
    masterbars = _parse_masterbars(root)   # list of [bar_id per track]

    result_tracks = []

    for track_idx, track_data in enumerate(tracks_raw):
        info = TrackInfo(
            index=track_idx,
            name=track_data["name"],
            channel=track_data["channel"],
        )

        # Each MasterBar has one bar ID per track; keep bar_ticks for rest-only bars
        bar_id_ticks = [
            (mb[0][track_idx], mb[1])
            for mb in masterbars
            if track_idx < len(mb[0]) and mb[0][track_idx] != "-1"
        ]

        current_tick = 0
        active_ties: dict = {}          # string → NoteEvent (タイ蓄積中)
        last_pitch: dict = {}           # string → 直前ノートのMIDIピッチ（H/P判定用）

        for bar_id, mb_ticks in bar_id_ticks:
            bar_info    = bars_map.get(bar_id, _BarInfo(voices=[], is_palm_mute=False, stroke=None))
            bar_voices  = bar_info.voices
            bar_pm      = bar_info.is_palm_mute
            bar_stroke  = bar_info.stroke
            bar_end_tick = current_tick

            for beat_ids in bar_voices:
                voice_tick = current_tick
                for beat_id in beat_ids:
                    beat = beats_map.get(beat_id)
                    if beat is None:
                        continue
                    dur = beat.rhythm_ticks

                    for nid in beat.note_ids:
                        note = notes_map.get(nid)
                        if note is None:
                            continue

                        if note.is_tie_dest:
                            # Extend the active tied note on this string
                            tied_evt = active_ties.get(note.string)
                            if tied_evt is not None:
                                tied_evt.duration_ticks += dur
                            # If this note is also a tie origin, keep it active;
                            # otherwise it's the last in the chain → emit it
                            if not note.is_tie_origin and tied_evt is not None:
                                info.events.append(active_ties.pop(note.string))
                        else:
                            # New note: close any previous tied note on this string
                            if note.string in active_ties:
                                info.events.append(active_ties.pop(note.string))

                            art = _resolve_art(note, beat,
                                               bar_palm_mute=bar_pm,
                                               bar_stroke=bar_stroke)

                            # H/P判定: HopoDestinationノートの場合、前の音より高い→HO、低い→PO
                            if note.is_hopo:
                                prev = last_pitch.get(note.string)
                                if prev is not None and note.midi_pitch < prev:
                                    art = "pull_off"
                                else:
                                    art = "hammer_on"

                            last_pitch[note.string] = note.midi_pitch

                            evt = NoteEvent(
                                tick=voice_tick,
                                duration_ticks=dur,
                                midi_pitch=note.midi_pitch,
                                velocity=beat.velocity,
                                articulation_id=art,
                                string_num=note.string,
                                bend_points=list(note.bend_points),
                            )

                            if note.is_tie_origin:
                                active_ties[note.string] = evt
                            else:
                                info.events.append(evt)

                    voice_tick += dur
                bar_end_tick = max(bar_end_tick, voice_tick)

            # 全ボイスが -1 の小節（全休符など）はMasterBarの拍子から長さを算出
            if bar_end_tick == current_tick:
                bar_end_tick = current_tick + mb_ticks

            current_tick = bar_end_tick

        # Flush any remaining tied notes at end of track
        for evt in active_ties.values():
            info.events.append(evt)

        result_tracks.append(info)

    return tempo, result_tracks
