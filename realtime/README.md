# Snowman Realtime

OpenAI Realtime API based voice assistant for Raspberry Pi.

## Goals

- Keep the custom pipeline app untouched in `../custom_pipeline/`
- Run on Raspberry Pi as a thin audio client
- Use local Porcupine wake word detection
- Stream audio directly to OpenAI Realtime over WebSocket
- Play model audio responses immediately
- Use explicit local turns with wake-word interruption during reply playback

## Setup

1. Create and activate a virtual environment:

```bash
cd realtime
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from the example:

```bash
cp .env.example .env
```

4. Fill in:

- `OPENAI_API_KEY`
- `PORCUPINE_ACCESS_KEY`
- audio and wake-word settings if needed
- `WAKE_WORD_SENSITIVITY` defaults to `0.65`; raise it carefully if wake-word interrupt misses during playback

## Run

```bash
./start_realtime.sh
```

This wrapper kills any older `main.py` instance first, then starts exactly one foreground process.

To bypass the wake word and repeatedly trigger turns automatically for debugging, set:

```bash
AUTO_TRIGGER_ENABLED=true
AUTO_TRIGGER_INTERVAL_SECONDS=0.0
AUTO_TRIGGER_MAX_SESSIONS=0
```

With that mode enabled, the app enters each turn directly and records the next utterance without waiting for `Snowman`.

To make that mode fully automated for connection testing, also enable synthetic utterances:

```bash
AUTO_TRIGGER_USE_SYNTHETIC_AUDIO=true
AUTO_TRIGGER_SYNTHETIC_AUDIO_MS=2500
```

## Probe Realtime Connectivity

Use the probe script to isolate Realtime connection reliability from the microphone pipeline:

```bash
python probe_realtime_connect.py --attempts 20
```

To test the next stage as well, including synthetic audio upload and response creation:

```bash
python probe_realtime_connect.py --attempts 20 --with-audio
```

To approximate the current app's upload style more closely, use chunked upload:

```bash
python probe_realtime_connect.py --attempts 20 --with-audio --audio-ms 2500 --upload-mode chunked-burst
```

To compare against a paced upload variant:

```bash
python probe_realtime_connect.py --attempts 20 --with-audio --audio-ms 2500 --upload-mode chunked-paced
```

## Raspberry Pi Notes

- The default playback path uses `aplay` with raw PCM.
- Wake word detection still uses a local `.ppn` file.
- Wake word sensitivity is controlled by `WAKE_WORD_SENSITIVITY` in the range `0.0` to `1.0`; higher values reduce misses but increase false triggers.
- The default custom wake word path points to `Snowman_en_raspberry-pi_v4_0_0.ppn` in this directory.
- The default ready cue uses `ready_cue.wav` in this directory.
- A post-reply cue can be configured with `POST_REPLY_CUE_PATH`; by default it reuses `ready_cue.wav`.
- A failure cue can be configured with `FAILURE_CUE_PATH`; by default it uses `wake_chime.wav`.
- The default playback device is auto-detected and prefers `Google voiceHAT`.
- The default mode uses manual turn submission to Realtime instead of continuous server VAD.
- During reply playback, the device only listens for the wake word; saying it again interrupts the current reply and starts a new turn.
- Model reply playback is software-attenuated with `OUTPUT_GAIN` to reduce speaker feedback on Raspberry Pi.
- Optional local input cleanup can be enabled with `INPUT_NS_ENABLED` and `INPUT_AGC_ENABLED`.
- The current `NS/AGC` path is lightweight local preprocessing designed to be safe on Raspberry Pi and easy to disable if it hurts recognition.
- Realtime connection/setup now uses configurable timeouts and exponential retry backoff, with three total attempts by default.

## Service

An example systemd unit is included at `snowman-realtime.service`.
It uses `start_realtime.sh` so service restarts also replace any older leftover instance.
