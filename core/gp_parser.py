"""
Parses GuitarPro files (.gp, .gpx, .gp5) using the guitarpro library.
Returns a list of NoteEvent objects with timing and articulation info.
"""
from dataclasses import dataclass, field
from typing import Optional
import guitarpro


@dataclass
class NoteEvent:
    """A single note with its position in ticks and detected articulation."""
    tick: int
    duration_ticks: int
    midi_pitch: int          # The actual pitch of the note
    velocity: int
    articulation_id: str     # canonical articulation key
    string_num: int = 0      # 1-based string number (0 = unknown)
    # Raw flags for debugging
    raw_flags: dict = field(default_factory=dict)


@dataclass
class TrackInfo:
    index: int
    name: str
    channel: int
    events: list = field(default_factory=list)  # list of NoteEvent


def _detect_stroke(beat) -> Optional[str]:
    """Return 'down' or 'up' from beat stroke, or None."""
    if not hasattr(beat, 'stroke') or beat.stroke is None:
        return None
    stroke = beat.stroke
    # guitarpro: stroke.value = StrokeEffect enum
    sv = getattr(stroke, 'value', None)
    if sv is None:
        return None
    sv_str = str(sv).lower()
    if 'down' in sv_str:
        return 'down'
    if 'up' in sv_str:
        return 'up'
    return None


def _is_palm_mute(beat) -> bool:
    if not hasattr(beat, 'effect') or beat.effect is None:
        return False
    return getattr(beat.effect, 'palmMute', False)


def _detect_harmonic_type(note):
    """Return 'natural', 'pinch', 'artificial', or None."""
    if not hasattr(note, 'effect') or note.effect is None:
        return None
    h = getattr(note.effect, 'harmonic', None)
    if h is None:
        return None
    h_type = str(type(h).__name__).lower()
    if 'natural' in h_type:
        return 'natural'
    if 'pinch' in h_type or 'semi' in h_type:
        return 'pinch'
    if 'artificial' in h_type or 'tapped' in h_type or 'feedback' in h_type:
        return 'artificial'
    return 'natural'


def _detect_slides(note) -> list:
    """Return list of slide type strings from note.effect.slides."""
    if not hasattr(note, 'effect') or note.effect is None:
        return []
    slides = getattr(note.effect, 'slides', [])
    if not slides:
        return []
    result = []
    for s in slides:
        s_str = str(s).lower()
        if 'intofrombove' in s_str or 'fromabove' in s_str or 'fromplucked' in s_str:
            result.append('from_above')
        elif 'intofromblow' in s_str or 'frombelow' in s_str:
            result.append('from_below')
        elif 'outdownward' in s_str or 'downward' in s_str:
            result.append('to_down')
        elif 'outupward' in s_str or 'upward' in s_str:
            result.append('to_up')
        elif 'legato' in s_str:
            result.append('legato')
        elif 'shift' in s_str:
            result.append('shift')
        else:
            result.append('legato')
    return result


def _articulation_from_beat_note(beat, note, string_index: int) -> str:
    """Derive the canonical articulation ID from a beat+note combination."""
    # Note-level techniques take priority
    effect = getattr(note, 'effect', None)

    is_dead = getattr(note, 'type', None) is not None and \
              str(getattr(note, 'type', '')).lower() in ('dead', 'muted')

    is_hammer = effect and getattr(effect, 'hammer', False)
    is_pull = effect and getattr(effect, 'pullOff', False)
    slides = _detect_slides(note)
    harmonic = _detect_harmonic_type(note)
    bend = effect and getattr(effect, 'bend', None)

    palm_mute = _is_palm_mute(beat)
    stroke = _detect_stroke(beat)

    beat_effect = getattr(beat, 'effect', None)
    is_tremolo = beat_effect and getattr(beat_effect, 'tremoloPicking', None)
    is_vibrato = (beat_effect and getattr(beat_effect, 'vibrato', False)) or \
                 (effect and getattr(effect, 'vibrato', False))
    is_tap = beat_effect and getattr(beat_effect, 'tap', False)
    is_slap = beat_effect and getattr(beat_effect, 'slap', False)
    is_pop = beat_effect and getattr(beat_effect, 'pop', False)

    # Priority order
    if is_slap:
        return 'slap'
    if is_pop:
        return 'pop'
    if is_tap:
        return 'tapping'
    if harmonic == 'pinch':
        return 'pinch_harmonic'
    if harmonic == 'natural':
        return 'natural_harmonic'
    if harmonic == 'artificial':
        return 'artificial_harmonic'
    if is_tremolo:
        return 'tremolo_picked'
    if slides:
        return 'slide_auto'
    if is_hammer:
        return 'hammer_on'
    if is_pull:
        return 'pull_off'
    if bend:
        return 'bend_up_slow'
    if is_vibrato:
        return 'vibrato'
    if is_dead and palm_mute:
        if stroke == 'down':
            return 'palm_mute_dead_down'
        elif stroke == 'up':
            return 'palm_mute_dead_up'
        return 'palm_mute_dead_alt'
    if palm_mute:
        if stroke == 'down':
            return 'palm_mute_down'
        elif stroke == 'up':
            return 'palm_mute_up'
        return 'palm_mute_alt'
    if is_dead:
        return 'dead_note'
    if stroke == 'down':
        return 'down_picked'
    if stroke == 'up':
        return 'up_picked'
    return 'alternate_picked'


def _is_zip(filepath: str) -> bool:
    """GP7 (.gp) files are ZIP archives; detect by magic bytes."""
    try:
        with open(filepath, "rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False


def parse_gp_file(filepath: str) -> tuple:
    """
    Parse a GuitarPro file and return (song_or_tempo, [TrackInfo]).
    Automatically detects GP7 (ZIP-based) vs older formats.
    """
    if _is_zip(filepath):
        from .gp7_parser import parse_gp7_file
        tempo, tracks = parse_gp7_file(filepath)
        # Return a simple object that carries tempo so main_window stays compatible
        class _Song:
            pass
        song = _Song()
        song.tempo = tempo
        return song, tracks

    song = guitarpro.parse(filepath)
    ticks_per_beat = 960  # guitarpro internal resolution

    tracks = []
    for track_idx, track in enumerate(song.tracks):
        info = TrackInfo(
            index=track_idx,
            name=track.name or f"Track {track_idx + 1}",
            channel=track.channel.channel if track.channel else 0,
        )

        current_tick = 0
        for measure in track.measures:
            beat_tick = current_tick
            for voice in measure.voices:
                voice_tick = current_tick
                for beat in voice.beats:
                    duration_ticks = _beat_duration_ticks(beat, ticks_per_beat)
                    for note in beat.notes:
                        # note.value is the fret, note.string is 1-based
                        # The actual MIDI pitch: combine with tuning
                        midi_pitch = _note_to_midi(song, track, note)
                        articulation = _articulation_from_beat_note(beat, note, note.string)
                        velocity = getattr(beat, 'velocity', None)
                        if velocity is None:
                            velocity = getattr(note, 'velocity', 95)
                        # guitarpro velocity is enum; convert to int
                        if hasattr(velocity, 'value'):
                            velocity = velocity.value

                        evt = NoteEvent(
                            tick=voice_tick,
                            duration_ticks=duration_ticks,
                            midi_pitch=midi_pitch,
                            velocity=int(velocity),
                            articulation_id=articulation,
                            string_num=note.string,
                        )
                        info.events.append(evt)
                    voice_tick += duration_ticks
            # Advance current_tick by the measure's total duration
            # (sum of beats in first voice)
            if measure.voices and measure.voices[0].beats:
                measure_ticks = sum(
                    _beat_duration_ticks(b, ticks_per_beat)
                    for b in measure.voices[0].beats
                )
                current_tick += measure_ticks
            else:
                # Fallback: use time signature
                ts = measure.timeSignature
                current_tick += ticks_per_beat * ts.numerator * 4 // ts.denominator.value

        tracks.append(info)

    return song, tracks


def _beat_duration_ticks(beat, ticks_per_beat: int) -> int:
    """Convert beat duration to MIDI ticks."""
    dur = beat.duration
    # guitarpro Duration.value: 1=whole, 2=half, 4=quarter, 8=eighth, 16=sixteenth, 32=32nd, 64=64th
    base = ticks_per_beat * 4 // dur.value
    if dur.isDotted:
        base = base * 3 // 2
    elif dur.isDoubleDotted:
        base = base * 7 // 4
    tuplet = dur.tuplet
    if tuplet and tuplet.enters != tuplet.times:
        base = base * tuplet.times // tuplet.enters
    return max(1, base)


def _note_to_midi(song, track, note) -> int:
    """Calculate MIDI pitch from fret + tuning."""
    # GuitarString.value is the open tuning MIDI note
    strings = track.strings
    string_idx = note.string - 1  # 1-based → 0-based
    if 0 <= string_idx < len(strings):
        open_note = strings[string_idx].value
        fret = note.value
        return open_note + fret
    return 60  # fallback
