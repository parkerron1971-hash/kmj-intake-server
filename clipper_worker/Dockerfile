# Built from inside clipper_worker/: on Railway this folder is the service's
# Root Directory, so the backend's railway.toml and nixpacks.toml at the repo
# root are never read (2026-10-06: connected without it, the service started
# building the API with Nixpacks). Every COPY is relative to this folder.
#
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
COPY vendor/bridgeclip/engine/requirements.lock /app/clipper_worker/vendor/bridgeclip/engine/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r clipper_worker/vendor/bridgeclip/engine/requirements.lock
# Face recognition for the cover likeness meter: SFace from the OpenCV Model
# Zoo (Apache-2.0), pinned by checksum; the build fails on any other file.
RUN python -c "import hashlib, os, urllib.request; p = '/app/models/face_recognition_sface_2021dec.onnx'; os.makedirs('/app/models', exist_ok=True); urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx', p); h = hashlib.sha256(open(p, 'rb').read()).hexdigest(); assert h == '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79', h"
COPY . /app/clipper_worker
# The face detector must load, or every clip would be framed blind.
RUN python -c "import cv2; cv2.FaceDetectorYN.create('/app/clipper_worker/vendor/bridgeclip/engine/assets/models/face_detection_yunet_2023mar.onnx', '', (320, 320)); cv2.FaceRecognizerSF.create('/app/models/face_recognition_sface_2021dec.onnx', '')"
ENV PYTHONUNBUFFERED=1 HOME=/home/clipper CLIPPER_WORK_DIR=/home/clipper/jobs
RUN chown -R clipper:clipper /app /home/clipper
USER clipper
CMD ["python", "-m", "clipper_worker.service"]
