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

## Run

```bash
python main.py
```

## Raspberry Pi Notes

- The default playback path uses `aplay` with raw PCM.
- Wake word detection still uses a local `.ppn` file.
- The default custom wake word path points to `Snowman_en_raspberry-pi_v4_0_0.ppn` in this directory.
- The default ready cue uses `ready_cue.wav` in this directory.
- A post-reply cue can be configured with `POST_REPLY_CUE_PATH`; by default it reuses `ready_cue.wav`.
- A failure cue can be configured with `FAILURE_CUE_PATH`; by default it uses `wake_chime.wav`.
- The default playback device is auto-detected and prefers `Google voiceHAT`.
- The default mode uses manual turn submission to Realtime instead of continuous server VAD.
- During reply playback, the device only listens for the wake word; saying it again interrupts the current reply and starts a new turn.
- Model reply playback is software-attenuated with `OUTPUT_GAIN` to reduce speaker feedback on Raspberry Pi.
- Realtime connection/setup is retried once by default before the app gives up on the current turn.

## Service

An example systemd unit is included at `snowman-realtime.service`.
