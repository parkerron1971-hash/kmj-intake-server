# The relay agent: Python + ffmpeg (Debian's ffmpeg has TLS, which
# rtmps:// to YouTube and Facebook needs). Copies only — no re-encoding.
# Runs as its own user (10001), never root (Codex R8).
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin relay
WORKDIR /app
COPY agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agent/relay_agent.py /app/relay_agent.py
USER 10001:10001
CMD ["python", "-u", "/app/relay_agent.py"]
