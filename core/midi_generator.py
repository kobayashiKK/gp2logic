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

# CC envelope resolution for strings mode (steps per beat, clamped 4–64 per note)
CC_STEPS_PER_BEAT = 16


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


def _build_vibrato_messages(event, abs_tick: int, dur_ticks: int,
                            channel: int, tempo_bpm: float) -> list:
    """
    Generate oscillating pitch-bend messages to simulate left-hand vibrato.

    Guitar Pro stores vibrato as <Vibrato>Slight</Vibrato> or <Vibrato>Wide</Vibrato>
    on the Note element.  We express it the same way as choking — pitch-bend messages —
    so no additional keyswitch or sampler configuration is required.

    Amplitude builds naturally from 0 → full depth via a smoothstep envelope,
    mimicking how a real guitarist develops vibrato after plucking the string:
    slight initial silence → gradual build-up over several cycles → full depth.

    Parameters (tunable constants at top of function):
      rate_hz         – oscillation frequency (typical guitar: 5–6 Hz)
      attack_secs     – initial silence before vibrato begins
      ramp_cycles     – oscillation cycles over which amplitude grows 0 → full
      depth_cents     – peak deviation in cents (Slight ≈ 50 ¢, Wide ≈ 100 ¢)
      steps_per_cycle – pitch-bend resolution per oscillation cycle
    """
    import math

    vib_type = getattr(event, 'vibrato_type', None)
    if not vib_type:
        return []

    # ── Tunable parameters ────────────────────────────────────────────────────
    RATE_HZ         = 5.5    # oscillation frequency (Hz)
    ATTACK_SECS     = 0.05   # initial silence before vibrato begins (seconds)
    RAMP_CYCLES     = 3.5    # oscillation cycles to grow from 0 → full depth
    STEPS_PER_CYCLE = 16     # pitch-bend messages per full oscillation cycle
    DEPTH_CENTS     = 100.0 if vib_type == "Wide" else 50.0  # ±cents at full depth
    # ─────────────────────────────────────────────────────────────────────────

    ticks_per_sec   = TICKS_PER_BEAT * tempo_bpm / 60.0
    attack_ticks    = int(ticks_per_sec * ATTACK_SECS)
    ticks_per_cycle = ticks_per_sec / RATE_HZ
    step_ticks      = max(1, int(ticks_per_cycle / STEPS_PER_CYCLE))
    ramp_ticks      = RAMP_CYCLES * ticks_per_cycle   # ticks to reach full depth

    # Peak depth in pitch-wheel units (PITCH_BEND_RANGE_SEMITONES semitones = ±8191)
    # This is the maximum upward deviation; vibrato never goes below natural pitch.
    pb_peak = int(DEPTH_CENTS / 100.0 / PITCH_BEND_RANGE_SEMITONES * 8191)

    msgs = []
    # Reset to natural pitch at note start (covers the silent attack phase)
    msgs.append((abs_tick, mido.Message('pitchwheel', channel=channel, pitch=0, time=0)))

    vib_start = abs_tick + attack_ticks
    t         = vib_start
    end_t     = abs_tick + dur_ticks
    angle     = 0.0

    while t < end_t - step_ticks:
        elapsed = t - vib_start
        # Smooth amplitude envelope: grows 0 → 1 over ramp_ticks via smoothstep
        # (slow start → fast middle → slow finish — natural left-hand feel)
        raw      = min(1.0, elapsed / ramp_ticks) if ramp_ticks > 0 else 1.0
        envelope = raw * raw * (3.0 - 2.0 * raw)   # smoothstep

        # Guitar vibrato only bends UP — pitch oscillates between 0 and +peak.
        # (1 - cos) / 2 gives a smooth 0→1→0 wave starting and ending at 0,
        # unlike sin which swings through negative values (unnatural for guitar).
        wave = (1.0 - math.cos(angle)) / 2.0        # range: 0.0 → 1.0
        pb   = int(pb_peak * envelope * wave)
        msgs.append((t, mido.Message('pitchwheel', channel=channel, pitch=pb, time=0)))
        angle += 2.0 * math.pi / STEPS_PER_CYCLE
        t     += step_ticks

    # Reset to natural pitch 1 tick after note-off
    msgs.append((end_t + 1, mido.Message('pitchwheel', channel=channel, pitch=0, time=0)))

    return msgs


def _interp_curve(points: list, t: float) -> float:
    """
    Linearly interpolate a list of (frac, value) control points at position t ∈ [0, 1].
    Points must be sorted by frac ascending.
    """
    if t <= points[0][0]:
        return float(points[0][1])
    if t >= points[-1][0]:
        return float(points[-1][1])
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t0 <= t <= t1:
            alpha = (t - t0) / (t1 - t0)
            return v0 + alpha * (v1 - v0)
    return float(points[-1][1])


def _build_all_strings_cc_messages(events: list, channel: int) -> list:
    """
    Build a continuous CC1 (modulation) + CC11 (expression) envelope
    that flows across ALL notes in sequence — no resets between notes.

    Both CC11 (Expression) and CC1 (Modulation) control dynamics/intensity in
    most string libraries — CC1 is bow pressure / sound character, not vibrato
    (vibrato is handled separately via pitch bend).  Both follow a similar
    swell-and-decay arc, with CC1 peaking slightly earlier to give the natural
    feel of bow pressure driving the tone before the full volume blooms.

    Each note's curve starts from the previous note's final CC values so
    dynamics connect naturally (legato feel).  Rests are bridged with a
    smooth glide: both CC11 and CC1 drift gently downward during silence.

    Curve shapes by note length
    ───────────────────────────
    Short  (< 0.5 beat):  crisp swell triangle
    Medium (0.5–2 beats): attack bloom → sustain → slight taper
    Long   (> 2 beats):   slow bloom → peak → natural decay

    The first control point of each note's curve is replaced by the previous
    note's end value, creating seamless CC continuity across note boundaries.
    """
    msgs = []
    sorted_evs = sorted(events, key=lambda e: e.tick)

    # Initial CC state at MIDI tick 0 (neutral, no sound yet)
    prev_exp      = 64
    prev_mod      = 56   # CC1 starts slightly lower than CC11
    prev_end_tick = 0

    # Emit initial reset so playback always starts clean
    msgs.append((0, mido.Message('control_change', channel=channel,
                                 control=11, value=prev_exp, time=0)))
    msgs.append((0, mido.Message('control_change', channel=channel,
                                 control=1,  value=prev_mod, time=0)))

    for event in sorted_evs:
        abs_tick  = _scale_tick(event.tick)
        dur_ticks = max(1, _scale_tick(event.duration_ticks))
        beats     = dur_ticks / TICKS_PER_BEAT

        # ── Bridge any rest gap before this note ─────────────────────
        gap = abs_tick - prev_end_tick
        if gap > 60:   # ignore sub-1/8-beat rounding gaps
            glide_steps = max(2, min(16, gap * CC_STEPS_PER_BEAT // TICKS_PER_BEAT))
            rest_exp = max(52, prev_exp - 14)   # gently drift downward during rest
            rest_mod = max(44, prev_mod - 14)   # CC1 drifts similarly
            for s in range(1, glide_steps + 1):
                frac = s / glide_steps
                tick = prev_end_tick + int(frac * gap)
                if tick >= abs_tick:
                    break
                msgs.append((tick, mido.Message('control_change', channel=channel,
                                                control=11,
                                                value=max(0, min(127, int(prev_exp + frac * (rest_exp - prev_exp)))),
                                                time=0)))
                msgs.append((tick, mido.Message('control_change', channel=channel,
                                                control=1,
                                                value=max(0, min(127, int(prev_mod + frac * (rest_mod - prev_mod)))),
                                                time=0)))
            prev_exp = rest_exp
            prev_mod = rest_mod

        # ── Note curve: start anchored at prev_exp / prev_mod ────────
        # CC1 peaks slightly earlier than CC11 (bow pressure drives tone first),
        # and its peak sits a few counts lower (pressure ≈ intensity, not raw volume).
        if beats < 0.5:
            # Short — crisp swell
            exp_pts = [(0.0, prev_exp), (0.25,  98), (0.60,  92), (1.0,  62)]
            mod_pts = [(0.0, prev_mod), (0.20,  92), (0.55,  84), (1.0,  56)]
        elif beats < 2.0:
            # Medium — attack bloom → sustain → slight taper
            exp_pts = [(0.0, prev_exp), (0.20, 104), (0.60, 108), (0.82, 98), (1.0, 74)]
            mod_pts = [(0.0, prev_mod), (0.16, 100), (0.55, 103), (0.78, 92), (1.0, 68)]
        else:
            # Long — slow bloom → peak → natural decay
            exp_pts = [(0.0, prev_exp), (0.12, 100), (0.40, 114),
                       (0.72, 112), (0.90,  96), (1.0, 78)]
            mod_pts = [(0.0, prev_mod), (0.10,  95), (0.36, 108),
                       (0.68, 106), (0.86,  90), (1.0, 72)]

        steps = int(max(4, min(64, beats * CC_STEPS_PER_BEAT)))
        for s in range(steps + 1):
            frac = s / steps
            tick = abs_tick + int(frac * dur_ticks)
            exp_val = int(max(0, min(127, _interp_curve(exp_pts, frac))))
            mod_val = int(max(0, min(127, _interp_curve(mod_pts, frac))))
            msgs.append((tick, mido.Message('control_change', channel=channel,
                                            control=11, value=exp_val, time=0)))
            msgs.append((tick, mido.Message('control_change', channel=channel,
                                            control=1,  value=mod_val, time=0)))

        # Carry end values to the next note
        prev_exp      = int(max(0, min(127, _interp_curve(exp_pts, 1.0))))
        prev_mod      = int(max(0, min(127, _interp_curve(mod_pts, 1.0))))
        prev_end_tick = abs_tick + dur_ticks

    return msgs


def _apply_let_ring(events: list) -> list:
    """Extend duration of let-ring notes so each note rings until the next
    note on the *same string* starts, capped at the start of any non-let-ring
    note that appears anywhere in the track.

    Guitar Pro let ring semantics:
    - A let ring note rings beyond its written duration.
    - It stops when a new note starts on the same string.
    - When the let ring "section" ends (i.e. the next beat in the score has
      let ring turned off), all ringing notes on every string must stop at
      that boundary — even strings that have no new note in the non-LR section.

    Two constraints are therefore applied simultaneously; the earlier one wins:
      1. Next note on the same string  (string continuity rule)
      2. First non-let-ring note anywhere in the track after this note
         (section boundary rule — captures the "let ring turned off" moment)

    This function mutates duration_ticks in-place and returns the list.
    """
    if not any(getattr(e, 'is_let_ring', False) for e in events):
        return events  # fast-path: no let-ring notes in this track

    sorted_evs = sorted(events, key=lambda e: e.tick)
    n = len(sorted_evs)

    for i, ev in enumerate(sorted_evs):
        if not getattr(ev, 'is_let_ring', False):
            continue

        # Constraint 1: next note on the same string
        next_string_tick = None
        for j in range(i + 1, n):
            if sorted_evs[j].tick > ev.tick and sorted_evs[j].string_num == ev.string_num:
                next_string_tick = sorted_evs[j].tick
                break

        # Constraint 2: first non-let-ring note on ANY string after this note
        # (marks the "let ring off" section boundary)
        cap_tick = None
        for j in range(i + 1, n):
            if sorted_evs[j].tick > ev.tick and not getattr(sorted_evs[j], 'is_let_ring', False):
                cap_tick = sorted_evs[j].tick
                break

        # Choose the tighter of the two constraints
        candidates = [t for t in (next_string_tick, cap_tick) if t is not None]
        if not candidates:
            continue  # no constraint — keep original written duration

        end_tick = min(candidates)
        new_dur = end_tick - ev.tick
        if new_dur > ev.duration_ticks:
            ev.duration_ticks = new_dur

    return events


def _velocity_for_event(event, mapping: KeyswitchMapping) -> tuple:
    """Return (velocity, articulation_id).
    Velocity triggers have been removed — articulation comes entirely from GPIF
    technique detection (note/beat/bar level).  Velocity only affects note loudness.
    """
    return event.velocity, event.articulation_id


def generate_midi(
    events: list,
    mapping: KeyswitchMapping,
    tempo_bpm: float = 120.0,
    midi_channel: int = 0,
    keyswitch_channel: int = 0,
    pitch_offset: int = 0,
    strings_mode: bool = False,
) -> bytes:
    """
    Build a .mid file from NoteEvents + KeyswitchMapping.
    - Keyswitches:   inserted 1 tick before each articulation change, same track
    - Pitch bend:    generated for notes with bend_points or vibrato_type
    - strings_mode:  when True, adds CC1 (modulation) and CC11 (expression)
                     envelopes shaped to each note's duration for realism
    """
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))

    messages = []   # (abs_tick, msg)

    default_art = getattr(mapping, 'default_articulation', '')

    # Let ring: extend note durations before anything else so CC envelopes and
    # keyswitch timing also reflect the correct (extended) note lengths.
    events = _apply_let_ring(list(events))

    # Strings mode: build the complete, connected CC1/CC11 envelope in one pass
    # before processing individual notes (so per-note logic stays clean).
    if strings_mode:
        messages.extend(_build_all_strings_cc_messages(events, midi_channel))

    # Insert default keyswitch at MIDI start (tick 0) to initialize the sampler
    if default_art:
        ks_note = mapping.get_note(default_art)
        if ks_note is not None:
            messages.append((0, mido.Message('note_on',  channel=keyswitch_channel,
                                             note=ks_note, velocity=100, time=0)))
            messages.append((1, mido.Message('note_off', channel=keyswitch_channel,
                                             note=ks_note, velocity=0,   time=0)))

    # Treat the initial state as "default" so the first note doesn't redundantly re-insert
    last_articulation = default_art or None

    for event in sorted(events, key=lambda e: e.tick):
        abs_tick  = _scale_tick(event.tick)
        dur_ticks = max(1, _scale_tick(event.duration_ticks))
        vel, art  = _velocity_for_event(event, mapping)

        # Determine keyswitch: use the art's own mapping, or fall back to default
        ks_note = mapping.get_note(art)
        effective_art = art
        if ks_note is None and default_art:
            # No specific keyswitch for this articulation → use default as fallback
            ks_note = mapping.get_note(default_art)
            if ks_note is not None:
                effective_art = default_art

        if ks_note is not None and effective_art != last_articulation:
            ks_tick = max(0, abs_tick - 1)
            messages.append((ks_tick,     mido.Message('note_on',  channel=keyswitch_channel,
                                                        note=ks_note, velocity=100, time=0)))
            messages.append((ks_tick + 1, mido.Message('note_off', channel=keyswitch_channel,
                                                        note=ks_note, velocity=0,   time=0)))
            last_articulation = effective_art

        # Pitch bend: choking bend envelope
        messages.extend(_build_bend_messages(event, abs_tick, dur_ticks, midi_channel))

        # Pitch bend: left-hand vibrato LFO (Slight / Wide)
        messages.extend(_build_vibrato_messages(event, abs_tick, dur_ticks,
                                                midi_channel, tempo_bpm))

        # Note on / off
        pitch = event.midi_pitch + pitch_offset
        if 0 <= pitch <= 127:
            messages.append((abs_tick,            mido.Message('note_on',  channel=midi_channel,
                                                               note=pitch, velocity=vel, time=0)))
            messages.append((abs_tick + dur_ticks, mido.Message('note_off', channel=midi_channel,
                                                                note=pitch, velocity=0,   time=0)))

    # Sort: by tick, then CC/pitchwheel → note_off → note_on
    # control_change and pitchwheel must precede note_on at the same tick
    # so the sampler receives the correct state before triggering.
    _ORDER = {'control_change': 0, 'pitchwheel': 0, 'note_off': 1, 'note_on': 2}

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
