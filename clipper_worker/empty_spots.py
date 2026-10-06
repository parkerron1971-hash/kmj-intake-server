"""Find stretches of a finished clip where nobody is on screen.

The engine follows the speaker but sometimes parks the vertical frame on the
backdrop while the speaker walks. This check samples each finished clip four
times a second with the engine's own YuNet face detector and reports every run
of at least MIN_GAP seconds with no face, so the review screen can say
"Nobody on screen 0:05-0:20". Measured on a 63-minute sermon (2026-10-05): it
flagged 5 of 16 clips and every flagged spot was a real empty stage.
"""
import math
import subprocess
from pathlib import Path

FPS = 4
MIN_GAP = 2.0
SCORE = 0.6
DETECT_WIDTH = 360  # YuNet needs far less than the 1080-wide output
MODEL = Path(__file__).parent / 'vendor' / 'bridgeclip' / 'engine' / 'assets' / 'models' / 'face_detection_yunet_2023mar.onnx'

# Choosing the face close-up a cover is drawn from (see face_score).
SPREAD = 14            # moments sampled evenly across the clip, besides the poster's
MIN_FACE = 0.035       # face width as a share of the frame's short side; smaller is too few pixels to keep a likeness
FULL_FACE = 0.25       # ... and the share past which a bigger face adds nothing
MAX_TURN = 0.45        # nose off the eyes' midpoint, in eye-distances: past this the head is turned away
MIN_EYE_SPREAD = 0.25  # eye distance / face width: below this the eyes have collapsed into a profile
FRONT_SPREAD = 0.4     # ... and a face-on spread
MAX_TILT = 0.5         # one eye above the other, in eye-distances
SHARP_SIDE = 128       # sharpness is measured on the face scaled to this width, so sizes compare
EYES_BAND = 0.6        # ... over the top of the face box: brows and eyes, not the mouth
SHARP_HALF = 60.0      # the Laplacian variance that counts as half sharp


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


def closeup_box(full_w, full_h, x, y, w, h):
    """The 4:5 box around a face at (x, y, w, h): about three face-widths wide,
    narrower when the frame is too short or too narrow for that, so the shape
    stays 4:5. The face sits in the upper part, centred across."""
    crop_w = min(w * 3.0, full_w, full_h * 0.8)
    crop_h = crop_w * 1.25
    left = max(0.0, min(full_w - crop_w, x + w / 2 - crop_w / 2))
    top = max(0.0, min(full_h - crop_h, y - h * 0.9))
    return int(left), int(top), int(crop_w), int(crop_h)


def sample_times(at, window=1.5, start=None, end=None, spread=SPREAD):
    """When to look for the cover's face: five moments within `window` seconds
    of the poster moment `at`, plus `spread` moments evenly across the clip's
    [start, end] in the recording (the middle of each equal slice, so never a
    cut at either edge). Sorted, so the reader only seeks forward."""
    times = {round(max(0.0, at + offset), 2) for offset in (-window, -window / 2, 0.0, window / 2, window)}
    if start is not None and end is not None and end > start:
        step = (end - start) / spread
        times |= {round(max(0.0, start + step * (i + 0.5)), 2) for i in range(spread)}
    return sorted(times)


def face_score(face, frame_w, frame_h, sharpness):
    """How well one detected face would guide a cover that must look like the
    person: facing the camera, sharp, big and surely a face. `face` is a YuNet
    row in the frame's pixels (x, y, w, h, right eye, left eye, nose tip,
    right and left mouth corners, confidence); `sharpness` is face_sharpness().

        score = size * sure * frontal * sharp, from 0 to 1

    size: face width over the frame's short side, saturating at FULL_FACE
    (square-rooted: a bigger face helps, but never outweighs a turned head).
    sure: the detector's confidence above a coin flip, (c - 0.5) / 0.5; a hand
    or the microphone across the face lowers it. frontal: the nose tip near
    the midpoint of the eyes, the eyes level, and the eyes spread across the
    face (a profile collapses them). sharp: the Laplacian variance v as
    v / (v + SHARP_HALF). None for a face too small to keep a likeness or
    turned too far away to show it: never the cover's face.

    A smile bonus was tried on the sermon test footage and left out: the
    mouth-corner width moves as much with speech as with a smile."""
    w, h = float(face[2]), float(face[3])
    rex, rey, lex, ley, nose_x = (float(v) for v in face[4:9])
    confidence = float(face[14])
    short = min(frame_w, frame_h)
    if w <= 0 or h <= 0 or short <= 0 or w / short < MIN_FACE:
        return None
    eyes = math.hypot(lex - rex, ley - rey)
    if eyes <= 0:
        return None
    turn = abs(nose_x - (rex + lex) / 2) / eyes
    tilt = abs(ley - rey) / eyes
    eye_spread = eyes / w
    if turn > MAX_TURN or eye_spread < MIN_EYE_SPREAD:
        return None
    frontal = (1 - (turn / MAX_TURN) ** 2) * max(0.0, 1 - (tilt / MAX_TILT) ** 2) * min(1.0, eye_spread / FRONT_SPREAD)
    size = math.sqrt(min(1.0, w / short / FULL_FACE))
    sure = max(0.0, min(1.0, (confidence - 0.5) / 0.5))
    sharp = max(0.0, sharpness) / (max(0.0, sharpness) + SHARP_HALF)
    score = size * sure * frontal * sharp
    return score if score > 0 else None


def face_sharpness(frame, x, y, w, h):
    """Variance of the Laplacian of the grey upper face (brows, eyes, top of
    the nose: the top EYES_BAND of the box, so an open mouth's teeth don't
    count as sharpness), scaled to SHARP_SIDE wide first so faces of
    different sizes compare (a small face upscaled is soft, as it would be on
    the cover). 0.0 for a box outside the frame."""
    import cv2
    full_h, full_w = frame.shape[:2]
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(full_w, int(math.ceil(x + w))), min(full_h, int(math.ceil(y + h * EYES_BAND)))
    if right - left < 2 or bottom - top < 2:
        return 0.0
    grey = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    factor = SHARP_SIDE / grey.shape[1]
    grey = cv2.resize(grey, (SHARP_SIDE, max(2, round(grey.shape[0] * factor))),
                      interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def face_closeup(source, at, target, face_detector, window=1.5, start=None, end=None):
    """A head-and-shoulders close-up of the speaker from the recording, for
    designing a cover that looks like them (Kevin, 2026-10-06: "over 90
    percent looks"). It looks at the moments sample_times() gives (around the
    poster moment `at` and across the clip's [start, end] in the recording),
    takes the speaker as the largest face in each, and keeps the frame whose
    face scores best on face_score(): facing the camera, sharp, big, sure.
    Crops about three face-widths wide, 4:5, and scales small crops up to 1024
    tall. Returns the face size in pixels, or None (no usable face: no file)."""
    import cv2
    cap = cv2.VideoCapture(str(source))

    def frames():
        for moment in sample_times(at, window, start, end):
            cap.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
            ok, frame = cap.read()
            if ok:
                yield frame
    try:
        return pick_closeup(frames(), target, face_detector)
    finally:
        cap.release()


class FramesUnreadable(Exception):
    """The video could not be read (an expired or bad link, a network blip,
    an unreadable file): never the same as "no face in it"."""


READ_SECONDS = 60


def remote_frames(url, start, end, folder, count=SPREAD):
    """`count` frames spread across [start, end] of a video at `url`, read by
    ffmpeg over the network: it seeks with range requests, so only that
    stretch of the recording is fetched, never the whole file. Returns BGR
    frames; raises FramesUnreadable when ffmpeg fails or reads none."""
    length = max(0.5, float(end) - float(start))
    try:
        done = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-ss', f'{max(0.0, float(start)):.3f}', '-t', f'{length:.3f}',
                               '-i', url, '-vf', f'fps={count / length:.6f}', '-frames:v', str(count), '-q:v', '2',
                               str(Path(folder) / 'frame_%03d.jpg')], capture_output=True, timeout=READ_SECONDS)
    except subprocess.TimeoutExpired:
        raise FramesUnreadable('Reading the video took too long.') from None
    paths = sorted(Path(folder).glob('frame_*.jpg'))
    if done.returncode != 0 or not paths:
        raise FramesUnreadable('The video could not be read.')
    import cv2
    frames = [frame for frame in (cv2.imread(str(path)) for path in paths) if frame is not None]
    if not frames:
        raise FramesUnreadable('The video could not be read.')
    return frames


def pick_closeup(frames, target, face_detector):
    """The best face among `frames` (the speaker is the largest face in each,
    scored by face_score), cropped by closeup_box, scaled up to 1024 tall and
    written to `target` as JPEG. Returns the face size in pixels, or None."""
    import cv2
    best = None
    for frame in frames:
        height, width = frame.shape[:2]
        scale = min(1.0, 640 / width)
        small = cv2.resize(frame, (round(width * scale), round(height * scale))) if scale < 1 else frame
        face_detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = face_detector.detect(small)
        if faces is None or not len(faces):
            continue
        face = max(faces, key=lambda f: f[2] * f[3])
        full = [float(v) / scale for v in face[:14]] + [float(face[14])]
        x, y, w, h = full[:4]
        score = face_score(full, width, height, face_sharpness(frame, x, y, w, h))
        if score is not None and (best is None or score > best[0]):
            best = (score, frame, (x, y, w, h))
    if best is None:
        return None
    _, frame, (x, y, w, h) = best
    left, top, crop_w, crop_h = closeup_box(frame.shape[1], frame.shape[0], x, y, w, h)
    crop = frame[top:top + crop_h, left:left + crop_w]
    if crop.size == 0:
        return None
    if crop.shape[0] < 1024:
        factor = 1024 / crop.shape[0]
        crop = cv2.resize(crop, (round(crop.shape[1] * factor), 1024), interpolation=cv2.INTER_LANCZOS4)
    if not cv2.imwrite(str(target), crop, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        return None
    return round(w), round(h)


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
