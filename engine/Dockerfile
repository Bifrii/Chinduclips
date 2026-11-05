FROM node:22-bookworm-slim AS node_runtime
FROM python:3.11-slim-bookworm
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m clip && mkdir -p /data /home/clip/.cache && chown -R clip:clip /data /app /home/clip/.cache
USER clip
ENV DATA_DIR=/data PORT=8080 WHISPER_MODEL=small HF_HOME=/home/clip/.cache/huggingface
EXPOSE 8080
CMD ["python", "server.py"]
