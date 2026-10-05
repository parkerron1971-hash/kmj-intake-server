# FFmpeg 8.1.2 static build with libass (captions) and libx264. The same
# FFmpeg version the 2026-10-05 rehearsal ran on. Pinned by digest.
FROM mwader/static-ffmpeg:8.1.2@sha256:33f770f812cbfc3de96c547157fc9faf8bd95a36481753439ffa761045167585 AS ffmpeg

FROM python:3.12-slim-bookworm
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates fontconfig && rm -rf /var/lib/apt/lists/*
# Captions need the libass-backed `ass` filter; fail the build, not a job.
RUN ffmpeg -hide_banner -filters | grep -Eq '[[:space:]]ass[[:space:]]' && ffmpeg -hide_banner -encoders | grep -Eq 'libx264|libopenh264'
RUN useradd -m -u 10001 clipper
WORKDIR /app
COPY clipper_worker/vendor/bridgeclip/engine/requirements.lock /app/clipper_worker/vendor/bridgeclip/engine/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r clipper_worker/vendor/bridgeclip/engine/requirements.lock
COPY clipper_worker /app/clipper_worker
# The face detector must load, or every clip would be framed blind.
RUN python -c "import cv2; cv2.FaceDetectorYN.create('/app/clipper_worker/vendor/bridgeclip/engine/assets/models/face_detection_yunet_2023mar.onnx', '', (320, 320))"
ENV PYTHONUNBUFFERED=1 HOME=/home/clipper CLIPPER_WORK_DIR=/home/clipper/jobs
RUN chown -R clipper:clipper /app /home/clipper
USER clipper
CMD ["python", "-m", "clipper_worker.service"]
