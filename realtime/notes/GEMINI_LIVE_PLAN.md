# OpenAI Client Extraction and Gemini Live Integration Plan

## Summary

Refactor the current realtime implementation in two phases.

Phase 1 extracts the existing OpenAI-specific realtime client into its own module without changing behavior. The goal is to prove that the assistant, session-window flow, tools, logging, and failure handling still work exactly as they do now.

Phase 2 adds a separate Gemini Live client for single-turn voice sessions only. Gemini will use native `GoogleSearch` for current-information lookup and will continue to use the shared custom tool path for tools like `local_time`. The existing assistant/audio/wake-word/session logic remains shared.

## Key Changes

### Phase 1: Extract OpenAI client with zero behavior change

- Move the current OpenAI websocket implementation out of `realtime_client.py` into `openai_realtime_client.py`.
- Keep the existing public assistant-facing behavior unchanged:
  - same session startup
  - same manual turn submission flow
  - same event mapping into `events.py`
  - same tool call handling
  - same fast-fail handling for transcription and response failure
  - same diagnostics logging
- Reduce `realtime_client.py` to one of these shapes and choose this as the default:
  - a thin compatibility wrapper that re-exports the OpenAI client, or
  - a factory entrypoint that currently returns the OpenAI client
- Introduce a backend selector in config:
  - `VOICE_BACKEND=openai|gemini`
  - default `openai`
- Add a small client-construction boundary used by `assistant.py` so the assistant no longer imports an OpenAI-specific class directly.
- Do not introduce a heavy shared transport abstraction. Shared code should only cover:
  - assistant-facing event contract
  - backend selection and factory
  - optional shared helpers that are truly vendor-neutral

### Phase 2: Add Gemini Live single-turn client

- Add `gemini_live_client.py` as a separate implementation, not a copy of the OpenAI wire protocol.
- Gemini v1 scope is single-turn only:
  - wake word
  - ready cue
  - record one utterance
  - send to Gemini Live
  - receive reply
  - play reply
  - close session
- Do not support Gemini session-window mode in v1.
- If `VOICE_BACKEND=gemini` and `SESSION_WINDOW_ENABLED=true`, fail fast at startup with a clear config error.
- Gemini client responsibilities:
  - connect and authenticate with Gemini Live API
  - stream audio input in Gemini's native shape
  - mark user turn completion in Gemini's native way
  - parse Gemini output events and emit the shared events from `events.py`
  - map Gemini function-calling requests into `ToolCallRequested`
  - submit shared custom tool results back to Gemini in Gemini's native function-response format
- Use Gemini native `GoogleSearch` directly instead of the shared `web_search` function tool.
- Shared custom tools remain available on both backends through `tools.py`.
- Tool behavior by backend:
  - `openai`: keep `local_time` and `web_search`
  - `gemini`: expose `local_time` as a custom function and use native `GoogleSearch`; do not expose the shared `web_search` tool to Gemini
- Prompt and runtime instruction builder should become backend-aware only where needed:
  - OpenAI instructions continue to say "call `web_search` for current information"
  - Gemini instructions should instead say to use available search capability for current information, without naming `web_search`
- Add config needed for Gemini:
  - `GEMINI_API_KEY`
  - `GEMINI_LIVE_MODEL`
  - `GEMINI_VOICE`
- Preserve existing OpenAI config and defaults unchanged.

### Assistant and shared runtime boundaries

- Keep `assistant.py` as the shared orchestrator for:
  - wake word
  - mic capture
  - playback
  - LED states
  - NS and AGC
  - session state machine
  - tool execution flow
- Keep `events.py` as the shared event contract.
- Keep `ToolRegistry` shared, but make tool registration backend-aware:
  - shared registry still executes custom tools
  - backend-specific client chooses which tools and capabilities are advertised upstream
- Keep the existing wait-cue behavior only for the shared custom `web_search` tool on OpenAI.
- Gemini native `GoogleSearch` does not need to be routed through `ToolRegistry`; any search-wait cue for Gemini is out of scope for v1.

## Test Plan

- Phase 1 regression:
  - OpenAI single-turn still works end to end
  - OpenAI session-window still works end to end
  - tool call path still works for `local_time` and `web_search`
  - response failure and transcription failure still fast-fail
  - current diagnostics logging still appears
- Phase 2 Gemini validation:
  - Gemini single-turn audio reply works end to end
  - Gemini can use native `GoogleSearch` for current-information questions
  - Gemini can call shared custom `local_time`
  - playback works with Gemini audio output format after any required sample-rate handling
  - `VOICE_BACKEND=gemini` with session-window enabled fails clearly at startup
- Acceptance scenarios:
  - OpenAI backend behavior is unchanged after Phase 1
  - Gemini backend can answer "现在日本首相是谁" using native search
  - Gemini backend can answer "现在几点" using shared `local_time`
  - Switching `VOICE_BACKEND` changes provider without touching assistant logic

## Assumptions and defaults

- `VOICE_BACKEND` defaults to `openai`
- Gemini v1 is single-turn only
- Gemini uses native `GoogleSearch`; shared `web_search` remains OpenAI-only
- Shared custom tools are provider-agnostic and continue to live in `ToolRegistry`
- No attempt is made to unify OpenAI and Gemini wire protocols behind a deep common client abstraction
- Search and wait UX for Gemini native search is deferred until after basic Gemini single-turn stability is proven
