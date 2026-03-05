# Snowman

Snowman now has two separate apps:

- `custom_pipeline/`: the existing local-first assistant, frozen as a baseline
- `realtime/`: a new OpenAI Realtime API version for Raspberry Pi voice-agent work

## Layout

```text
snowman/
├── custom_pipeline/
├── realtime/
└── plans/
```

## Custom Pipeline App

The original app was moved intact into [`custom_pipeline/`](./custom_pipeline/README.md). It remains the fallback and comparison target while the new realtime path is developed.

## Realtime App

The new app lives in [`realtime/`](./realtime/README.md). Its v1 architecture is:

```text
Porcupine wake word -> Pi audio capture -> OpenAI Realtime WebSocket -> streamed audio playback
```

It is designed to run on the Raspberry Pi hardware that is already connected and reachable over SSH.
