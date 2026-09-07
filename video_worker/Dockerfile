FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 10001 renderer
WORKDIR /app
COPY video_worker/requirements.txt /app/video_worker/requirements.txt
RUN pip install --no-cache-dir -r video_worker/requirements.txt
COPY video_worker/package.json video_worker/package-lock.json /app/video_worker/
RUN cd video_worker && npm ci --omit=dev
COPY video_cloud_renderer.py /app/video_cloud_renderer.py
ENV HYPERFRAMES_NO_TELEMETRY=1 HYPERFRAMES_SKIP_SKILLS=1 HOME=/home/renderer PYTHONUNBUFFERED=1
RUN chown -R renderer:renderer /app /home/renderer
USER renderer
RUN cd video_worker && npx hyperframes browser ensure
CMD ["python","video_cloud_renderer.py"]
