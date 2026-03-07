# Snowman

Snowman now has two separate apps:

- `pipeline/`: the existing local-first assistant, frozen as a baseline
- `realtime/`: a new OpenAI Realtime API version for Raspberry Pi voice-agent work

## Layout

```text
snowman/
├── pipeline/
├── realtime/
└── plans/
```

## Custom Pipeline App

The original app was moved intact into [`pipeline/`](./pipeline/README.md). It remains the fallback and comparison target while the new realtime path is developed.

```mermaid
flowchart LR
    user["User"] --> wake["Porcupine wake word"]
    wake --> session["Conversation session controller"]
    session --> record["PvRecorder + Cobra VAD"]
    record --> stt["faster-whisper STT"]
    stt --> llm["Gemini response generation"]
    llm --> tts["Edge TTS"]
    tts --> speaker["Speaker playback"]
    llm -. optional .-> search["Tavily web search"]
    search -. context .-> llm
    speaker --> next["Next turn in session"]
    next --> session
    session -. timeout / goodbye .-> wake
```

## Realtime App

The new app lives in [`realtime/`](./realtime/README.md). Its v1 architecture is:

```mermaid
flowchart LR
    user["User"] --> wake["Porcupine wake word"]
    wake --> session["Session controller"]
    session --> mic["Pi microphone + local audio cleanup"]
    mic --> rt["OpenAI Realtime session over WebSocket"]
    rt --> tools["Tool calls: web_search / local_time"]
    tools --> rt
    rt --> speaker["Streamed reply playback"]
    speaker --> next["Next turn in half-duplex loop"]
    next --> session
```

It is designed to run on the Raspberry Pi hardware that is already connected and reachable over SSH.
