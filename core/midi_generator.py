"""
Generates a MIDI file from parsed NoteEvents with keyswitch notes inserted.
"""
import mido
from .technique_mapper import KeyswitchMapping, VelocityTrigger


TICKS_PER_BEAT = 480  # Standard MIDI resolution for output


def _scale_tick(gp_tick: int) -> int:
    """Scale from guitarpro 960 ticks/beat to output 480 ticks/beat."""
    return gp_tick // 2


def _velocity_for_event(event, mapping: KeyswitchMapping) -> tuple[int, str]:
    """
    Return (velocity, articulation_id) considering velocity triggers.
    Velocity triggers may override both the velocity and articulation.
    """
    vel = event.velocity
    art = event.articulation_id

    for vt in mapping.velocity_triggers:
        if vt.min_vel <= vel <= vt.max_vel:
            art = vt.articulation_id
            # Keep original velocity (the trigger selects articulation, not velocity)
            break

    return vel, art


def generate_midi(
    events: list,
    mapping: KeyswitchMapping,
    tempo_bpm: float = 120.0,
    midi_channel: int = 0,
    keyswitch_channel: int = 0,
) -> bytes:
    """
    Build a .mid file bytes from NoteEvents + KeyswitchMapping.

    Keyswitches are inserted on the same track and channel as notes.
    Each keyswitch fires 1 tick before the note it belongs to,
    only when the articulation changes.
    """
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))

    # Build absolute-time message list, then convert to delta times
    messages = []  # (abs_tick, msg)

    last_articulation = None

    # Sort events by tick
    sorted_events = sorted(events, key=lambda e: e.tick)

    for event in sorted_events:
        abs_tick = _scale_tick(event.tick)
        dur_ticks = max(1, _scale_tick(event.duration_ticks))
        vel, art = _velocity_for_event(event, mapping)

        # Insert keyswitch if articulation changed
        ks_note = mapping.get_note(art)
        if ks_note is not None and art != last_articulation:
            ks_tick = max(0, abs_tick - 1)
            messages.append((ks_tick, mido.Message('note_on',  channel=keyswitch_channel, note=ks_note, velocity=100, time=0)))
            messages.append((ks_tick + 1, mido.Message('note_off', channel=keyswitch_channel, note=ks_note, velocity=0,   time=0)))
            last_articulation = art

        # Note on/off
        pitch = event.midi_pitch
        if 0 <= pitch <= 127:
            messages.append((abs_tick,             mido.Message('note_on',  channel=midi_channel, note=pitch, velocity=vel, time=0)))
            messages.append((abs_tick + dur_ticks,  mido.Message('note_off', channel=midi_channel, note=pitch, velocity=0,   time=0)))

    # Sort by absolute tick, then note_off before note_on at same tick
    def sort_key(item):
        tick, msg = item
        order = 0 if msg.type == 'note_off' else 1
        return (tick, order)

    messages.sort(key=sort_key)

    # Convert to delta time
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
