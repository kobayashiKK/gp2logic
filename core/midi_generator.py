"""
Generates a MIDI file from parsed NoteEvents with keyswitch notes inserted.
"""
import mido
from .technique_mapper import KeyswitchMapping

TICKS_PER_BEAT = 480  # Output MIDI resolution

# Pitch bend range used when generating bend events (semitones).
# Must match the receiving instrument's pitch bend sensitivity setting.
PITCH_BEND_RANGE_SEMITONES = 2

# Number of pitch bend interpolation steps per beat (higher = smoother)
BEND_STEPS_PER_BEAT = 16


def _scale_tick(gp_tick: int) -> int:
    """Scale from GP7 960 ticks/beat to output 480 ticks/beat."""
    return gp_tick // 2


def _semitones_to_pitchwheel(semitones: float) -> int:
    """Convert semitone offset to MIDI pitch wheel value (center=0 in mido)."""
    ratio = semitones / PITCH_BEND_RANGE_SEMITONES
    ratio = max(-1.0, min(1.0, ratio))
    return int(ratio * 8191)


def _build_bend_messages(event, abs_tick: int, dur_ticks: int, channel: int) -> list:
    """
    Generate pitch bend messages for a note with bend_points.
    Returns list of (abs_tick, mido.Message).
    """
    if not event.bend_points:
        return []

    msgs = []
    points = event.bend_points  # list of BendPoint(offset_frac, semitones)

    # Initial reset to center at note start
    msgs.append((abs_tick, mido.Message('pitchwheel', channel=channel, pitch=0, time=0)))

    # Interpolate between bend points
    for i in range(len(points) - 1):
        p0 = points[i]
        p1 = points[i + 1]
        t0 = abs_tick + int(p0.offset_frac * dur_ticks)
        t1 = abs_tick + int(p1.offset_frac * dur_ticks)
        if t1 <= t0:
            continue

        steps = max(1, (t1 - t0) * BEND_STEPS_PER_BEAT // TICKS_PER_BEAT)
        for s in range(steps + 1):
            frac = s / steps
            sem = p0.semitones + frac * (p1.semitones - p0.semitones)
            tick = t0 + int(frac * (t1 - t0))
            pw = _semitones_to_pitchwheel(sem)
            msgs.append((tick, mido.Message('pitchwheel', channel=channel, pitch=pw, time=0)))

    # Hold final value through rest of note, then reset after note ends
    last_sem = points[-1].semitones
    last_pw = _semitones_to_pitchwheel(last_sem)
    last_t = abs_tick + int(points[-1].offset_frac * dur_ticks)
    msgs.append((last_t, mido.Message('pitchwheel', channel=channel, pitch=last_pw, time=0)))
    # Reset to center 1 tick after note_off
    msgs.append((abs_tick + dur_ticks + 1,
                 mido.Message('pitchwheel', channel=channel, pitch=0, time=0)))

    return msgs


# Velocityトリガーで上書き可能な「汎用ピッキング系」奏法
_VEL_OVERRIDABLE = {
    "alternate_picked", "down_picked", "up_picked",
    "palm_mute_down", "palm_mute_up", "palm_mute_alt",
}

def _velocity_for_event(event, mapping: KeyswitchMapping) -> tuple:
    vel = event.velocity
    art = event.articulation_id
    # H/P・ハーモニクス・スライド等の固有奏法はvelocityトリガーで上書きしない
    if art in _VEL_OVERRIDABLE:
        for vt in mapping.velocity_triggers:
            if vt.min_vel <= vel <= vt.max_vel:
                art = vt.articulation_id
                break
    return vel, art


def generate_midi(
    events: list,
    mapping: KeyswitchMapping,
    tempo_bpm: float = 120.0,
    midi_channel: int = 0,
    keyswitch_channel: int = 0,
    pitch_offset: int = 0,
) -> bytes:
    """
    Build a .mid file from NoteEvents + KeyswitchMapping.
    - Keyswitches: inserted 1 tick before each articulation change, same track
    - Pitch bend: generated for notes with bend_points
    """
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))

    messages = []   # (abs_tick, msg)

    # Insert default keyswitch at MIDI start (tick 0)
    default_art = getattr(mapping, 'default_articulation', '')
    if default_art:
        ks_note = mapping.get_note(default_art)
        if ks_note is not None:
            messages.append((0, mido.Message('note_on',  channel=keyswitch_channel,
                                             note=ks_note, velocity=100, time=0)))
            messages.append((1, mido.Message('note_off', channel=keyswitch_channel,
                                             note=ks_note, velocity=0,   time=0)))

    last_articulation = default_art or None

    for event in sorted(events, key=lambda e: e.tick):
        abs_tick  = _scale_tick(event.tick)
        dur_ticks = max(1, _scale_tick(event.duration_ticks))
        vel, art  = _velocity_for_event(event, mapping)

        # Keyswitch on articulation change
        ks_note = mapping.get_note(art)
        if ks_note is not None and art != last_articulation:
            ks_tick = max(0, abs_tick - 1)
            messages.append((ks_tick,     mido.Message('note_on',  channel=keyswitch_channel,
                                                        note=ks_note, velocity=100, time=0)))
            messages.append((ks_tick + 1, mido.Message('note_off', channel=keyswitch_channel,
                                                        note=ks_note, velocity=0,   time=0)))
            last_articulation = art

        # Pitch bend events
        messages.extend(_build_bend_messages(event, abs_tick, dur_ticks, midi_channel))

        # Note on / off
        pitch = event.midi_pitch + pitch_offset
        if 0 <= pitch <= 127:
            messages.append((abs_tick,            mido.Message('note_on',  channel=midi_channel,
                                                               note=pitch, velocity=vel, time=0)))
            messages.append((abs_tick + dur_ticks, mido.Message('note_off', channel=midi_channel,
                                                                note=pitch, velocity=0,   time=0)))

    # Sort: by tick, then note_off before note_on, pitchwheel before note_on
    _ORDER = {'pitchwheel': 0, 'note_off': 1, 'note_on': 2}

    def _sort_key(item):
        tick, msg = item
        return (tick, _ORDER.get(msg.type, 3))

    messages.sort(key=_sort_key)

    prev_tick = 0
    for abs_tick, msg in messages:
        delta = abs_tick - prev_tick
        track.append(msg.copy(time=delta))
        prev_tick = abs_tick

    track.append(mido.MetaMessage('end_of_track', time=0))

    import io
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()
