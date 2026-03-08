# Realtime Session Window Plan

## Goal

Build a Raspberry Pi voice assistant that is:

- stable on real hardware
- based on OpenAI Realtime API
- suitable for portfolio/demo use
- capable of short multi-turn conversation without falling into self-feedback

The current priority is not full-duplex conversation. The priority is a reliable voice loop on Raspberry Pi.

## Current Stable Baseline

The current `realtime/` app uses a single-turn flow:

1. wait for local wake word
2. play a very short ready cue
3. record one utterance locally
4. open a Realtime session
5. upload the recorded audio
6. play the model response
7. close the Realtime session
8. return to wake-word idle

This is intentionally conservative. It avoids the main failure mode seen on the Pi: the assistant hearing its own reply.

## Problem We Are Solving Next

The single-turn flow is stable, but it is not a good final interaction model because:

- the user must say the wake word before every turn
- the assistant cannot naturally handle short follow-up questions
- the current UX feels more transactional than conversational

At the same time, going back to a continuously open microphone is not acceptable on this hardware because it caused:

- self-triggered follow-up replies
- speaker-to-microphone feedback
- unstable interruption behavior

## Near-Term Audio Strategy

Before attempting full-duplex audio again, improve the local input chain first.

Near-term priority order:

1. keep the current half-duplex interaction stable
2. add local `NS` and `AGC` if they can be introduced safely on Raspberry Pi
3. evaluate `AEC` only after playback and capture are routed through an audio stack that can provide a reliable playback reference
4. revisit continuous full-duplex audio only after the above is validated on real hardware

This order matters because:

- `NS` and `AGC` can improve transcript quality and turn detection without reopening the main self-feedback failure mode
- `AEC` is the real requirement for open-speaker full-duplex, but it is only useful if the playback reference path is available and stable
- changing protocol alone, such as switching from WebSocket to WebRTC, does not remove the need for reliable local echo control on Raspberry Pi

## Near-Term Product Direction

The current path remains centered on OpenAI Realtime API.

For the next iteration:

- keep Realtime as the primary conversation layer
- add direct tool support for current-information questions, starting with `web search`
- add simple utility tools as needed, such as current local time
- defer any `pi-mono` integration until the core Realtime voice loop and tool flow are working reliably

This keeps the architecture simple while we validate:

- whether Realtime function calling is sufficient for the near-term product goals
- whether current-information questions can be handled well without introducing a second agent runtime
- whether the Raspberry Pi voice experience remains responsive once tools are added

## Target Design

Move from a single-turn flow to a short session-window flow.

The key idea is:

- keep one Realtime session alive for a short conversation window
- do **not** keep the microphone continuously open
- keep audio interaction half-duplex:
  - when listening, do not speak
  - when speaking, do not listen

This keeps short-term conversational memory inside one Realtime session without reintroducing the self-feedback problem.

## Proposed Interaction Model

### Session Start

1. local wake word is detected
2. start one Realtime session
3. play a short ready cue
4. record one user utterance
5. submit it to the active Realtime session

### Within The Session Window

For each turn:

1. record one utterance locally
2. commit audio to the existing Realtime session
3. request one reply
4. play the reply fully
5. play a short ready cue
6. listen for the next utterance

### Session End

Close the Realtime session when any of these happens:

- user says an end phrase such as `bye` or `再见`
- no new utterance arrives before the session-window timeout
- the Realtime connection errors or closes
- the user explicitly interrupts and we decide to end the current window

## Why Keep Half-Duplex Audio

The session should persist, but the microphone should not stay live all the time.

That distinction is important:

- `session persistence` gives the model short-term memory
- `microphone gating` gives the device stability

So the next design is:

- persistent session
- turn-based audio capture
- no continuous upstream microphone audio during reply playback

## Interruption Model

Interruption should remain explicit and local-first.

During assistant reply playback:

- normal microphone upload stays off
- local wake word detection stays on

If the wake word is heard during playback:

1. interrupt current reply playback
2. clear or cancel the active response
3. play the short ready cue
4. start recording the next user utterance
5. continue within the same session window if possible

## Memory Model

### Short-Term Memory

Short-term conversational memory should come from keeping the same Realtime session alive across multiple turns within one session window.

### Cross-Window Memory

Cross-window memory should not depend on an old session surviving.

Instead, maintain local state such as:

- recent user transcripts
- recent assistant transcripts
- optional compact session summary

That local memory can later be injected into a new session if needed.

## Immediate Implementation Plan

### Phase 1: Keep Current Single-Turn Stable

- keep current single-turn mode as the fallback baseline
- continue validating cue playback, recording thresholds, and reply playback

### Phase 2: Add Input Cleanup With NS/AGC

- evaluate a Raspberry Pi compatible audio path that can add local `NS` and `AGC`
- keep this optional behind configuration so the current stable baseline remains available
- measure whether transcript quality and wake-to-turn reliability improve on real hardware

### Phase 3: Add Realtime Tools For Current Information

- add a direct tool path for current-information questions, starting with `web search`
- add a simple local time tool for `what time is it` style questions
- keep tool definitions and tool routing inside the Realtime client for now
- measure added latency and confirm that interruptions and playback remain stable

### Phase 4: Add Session Window State Machine

Introduce explicit states:

- `idle`
- `ready`
- `recording_turn`
- `waiting_for_reply`
- `playing_reply`
- `session_timeout`
- `session_end`

### Phase 5: Keep One Realtime Session Across Multiple Turns

- open the session once per wake event
- reuse it across follow-up turns
- close it only when the session window ends

### Phase 6: Add Ready Cue After Reply Playback

- after reply playback completes, play the short ready cue
- then reopen local recording for the next user turn

### Phase 7: Keep Local Wake-Word Interrupt During Playback

- do not reopen general mic upload during playback
- only keep local wake-word detection active during reply playback

### Phase 8: Revisit AEC And Full-Duplex Only If Audio Routing Supports It

- do not treat protocol changes alone as a fix for self-feedback
- only evaluate `AEC` if playback output and microphone capture share an audio path that can provide a stable playback reference
- only retry continuous full-duplex after `NS/AGC` and routing changes are verified on Raspberry Pi

### Deferred: Evaluate pi-mono As A Secondary Agent Runtime

- do not introduce `pi-mono` into the primary path until direct Realtime tools are validated
- only revisit `pi-mono` if direct Realtime function calling proves too limited for local tools or multi-step task execution
- avoid split ownership of tools while the Realtime architecture is still being stabilized

## Guardrails

The following rules should remain in place while implementing the session window:

- no continuously open microphone during reply playback
- no automatic server-side open-mic turn detection as the primary mode
- no assumption that `VAD` or protocol changes alone will solve speaker echo
- no second agent runtime in the primary path until direct Realtime tools are proven insufficient
- every session must close cleanly on timeout, error, or normal completion
- logs must continue to show:
  - cue playback start/end
  - recording start/end
  - Realtime connect/close
  - first response audio latency
  - playback duration
  - total session duration

## Success Criteria

The next version is successful if it can do all of the following on Raspberry Pi:

- one wake word starts a short multi-turn session
- the user can ask a follow-up question without re-waking each time
- the assistant does not reply to its own voice
- transcript quality is improved by local input cleanup where enabled
- current-information questions can be answered reliably with direct Realtime tools
- the session times out cleanly when the user stops talking
- Realtime connections do not remain open unnecessarily
