"""Find stretches of a finished clip where nobody is on screen.

The engine follows the speaker but sometimes parks the vertical frame on the
backdrop while the speaker walks. This check samples each finished clip four
times a second with the engine's own YuNet face detector and reports every run
of at least MIN_GAP seconds with no face, so the review screen can say
"Nobody on screen 0:05-0:20". Measured on a 63-minute sermon (2026-10-05): it
flagged 5 of 16 clips and every flagged spot was a real empty stage.
"""
from pathlib import Path

FPS = 4
MIN_GAP = 2.0
SCORE = 0.6
DETECT_WIDTH = 360  # YuNet needs far less than the 1080-wide output
MODEL = Path(__file__).parent / 'vendor' / 'bridgeclip' / 'engine' / 'assets' / 'models' / 'face_detection_yunet_2023mar.onnx'


def gaps(samples, end, min_gap=MIN_GAP):
    """Runs without a face, from (seconds, has_face) samples in time order.

    A run still open at the last sample closes at `end`, the clip's length.
    """
    found, start = [], None
    for at, has_face in list(samples) + [(end, True)]:
        if not has_face and start is None:
            start = at
        elif has_face and start is not None:
            if at - start >= min_gap:
                found.append({'from': round(start, 1), 'to': round(at, 1), 'seconds': round(at - start, 1)})
            start = None
    return found


def detector():
    import cv2
    return cv2.FaceDetectorYN.create(str(MODEL), '', (DETECT_WIDTH, 640), SCORE, 0.3, 5000)


def poster_time(centred, length):
    """The poster frame: the moment in the first 60% (after the opening second
    or so) where a face sits closest to the middle of the frame. `centred` is
    (seconds, distance of the face from centre as a share of the width)."""
    opening = min(1.5, length * 0.15)
    window = [(distance, at) for at, distance in centred if opening <= at <= max(opening, length * 0.6)]
    if window:
        return min(window)[1]
    if centred:
        return centred[0][0]
    return min(1.0, length / 2)


def scan(path, face_detector):
    """Sample one clip. Returns its length, the share of samples with a face,
    the empty spots, and a poster moment where the speaker is in frame."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, round(fps / FPS))
        samples, centred, index = [], [], 0
        while cap.grab():
            if index % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                height, width = frame.shape[:2]
                small = cv2.resize(frame, (DETECT_WIDTH, round(height * DETECT_WIDTH / width)))
                face_detector.setInputSize((small.shape[1], small.shape[0]))
                _, faces = face_detector.detect(small)
                found = faces is not None and len(faces) > 0
                samples.append((index / fps, found))
                if found:
                    x, _, w = faces[0][0], faces[0][1], faces[0][2]
                    centred.append((index / fps, abs((x + w / 2) / small.shape[1] - 0.5)))
            index += 1
    finally:
        cap.release()
    length = frames / fps if frames else (samples[-1][0] if samples else 0.0)
    return {
        'length': round(length, 2),
        'face_coverage': round(len(centred) / len(samples), 3) if samples else 0.0,
        'empty_spots': gaps(samples, length),
        'poster_at': round(poster_time(centred, length), 2),
    }
