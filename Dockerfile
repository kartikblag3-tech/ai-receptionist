# AI Receptionist — production image (OpenAI Realtime voice agent).
# Runs the FastAPI Realtime server (gpt-realtime-2.1, sub-second, interruptible)
# on Fly.io free tier (always-on, $0) with a stable public URL.
FROM python:3.12-slim

WORKDIR /app

# ffmpeg is needed to convert audio (mu-law <-> wav) for whisper and TTS.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py pipeline_server.py tools.py webservices.py salon.py salon_demo.py osmora.py ./
RUN mkdir -p data

# Fly.io sets PORT; default to 5050 for local runs.
ENV PORT=5050
ENV BUSINESS_MODULE=salon_demo

EXPOSE 5050
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-5050}"]
