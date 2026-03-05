# Snowman Realtime

OpenAI Realtime API based voice assistant for Raspberry Pi.

## Goals

- Keep the custom pipeline app untouched in `../custom_pipeline/`
- Run on Raspberry Pi as a thin audio client
- Use local Porcupine wake word detection
- Stream audio directly to OpenAI Realtime over WebSocket
- Play model audio responses immediately
- Support basic interruption through server VAD and local playback reset

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
- The default custom wake word path points to `Snowman_en_raspberry-pi_v3_0_0.ppn` in this directory.

## Service

An example systemd unit is included at `snowman-realtime.service`.
