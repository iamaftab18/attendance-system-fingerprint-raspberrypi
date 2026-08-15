import os
import shutil

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
FACE_DATA_DIR = os.path.join(PROJECT_ROOT, 'face_data')
SAMPLES_DIR = os.path.join(FACE_DATA_DIR, 'samples')
MODEL_PATH = os.path.join(FACE_DATA_DIR, 'lbph_model.yml')
FACE_SIZE = (200, 200)
SAMPLES_PER_ENROLLMENT = 12

# LBPH predict() returns a distance, not a confidence score - lower means a
# closer match. Values above this are treated as "not recognized".
MATCH_DISTANCE_THRESHOLD = 70

_face_cascade = None
_eye_cascade = None
_eye_cascade_unavailable = False
_clahe = None

# Some ARM/piwheels OpenCV builds don't ship cv2.data.haarcascades with the
# XML files present, even though the module imports fine. The project ships
# its own copy (checked first) so face detection works regardless of how any
# given machine's OpenCV was packaged; the OpenCV/system paths are kept as a
# fallback for environments where re-cloning isn't convenient.
_CASCADE_SEARCH_DIRS = [
    os.path.join(PROJECT_ROOT, 'haarcascades'),
    cv2.data.haarcascades,
    '/usr/share/opencv4/haarcascades/',
    '/usr/share/opencv/haarcascades/',
    '/usr/local/share/opencv4/haarcascades/',
    os.path.join(os.path.dirname(cv2.__file__), 'data', ''),
]


def _find_cascade_file(filename):
    for directory in _CASCADE_SEARCH_DIRS:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            return path
    searched = ', '.join(_CASCADE_SEARCH_DIRS)
    raise RuntimeError(
        f"Haar cascade '{filename}' not found in any known OpenCV data directory "
        f"(searched: {searched}). Your OpenCV install is missing its data files - "
        f"fix with: pip install --force-reinstall --no-cache-dir opencv-contrib-python "
        f"(or: sudo apt install libopencv-data)."
    )


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        cascade = cv2.CascadeClassifier(_find_cascade_file('haarcascade_frontalface_default.xml'))
        if cascade.empty():
            raise RuntimeError('haarcascade_frontalface_default.xml was found but OpenCV could not load it (corrupted file?).')
        _face_cascade = cascade
    return _face_cascade


def _get_eye_cascade():
    """Eye detection is only used for alignment, which is an accuracy nice-to-have.
    Unlike the face cascade, a missing/broken eye cascade should never break
    enrollment or recognition - just disable alignment and fall back silently.
    """
    global _eye_cascade, _eye_cascade_unavailable
    if _eye_cascade is None and not _eye_cascade_unavailable:
        try:
            cascade = cv2.CascadeClassifier(_find_cascade_file('haarcascade_eye.xml'))
            if cascade.empty():
                raise RuntimeError('haarcascade_eye.xml found but failed to load')
            _eye_cascade = cascade
        except Exception as e:
            print(f'[FaceRecognizer] Eye cascade unavailable, face alignment disabled: {e}')
            _eye_cascade_unavailable = True
    return _eye_cascade


def _get_clahe():
    global _clahe
    if _clahe is None:
        _clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return _clahe


def _align_face(gray, x, y, w, h):
    """Rotate the face crop so the eye line is horizontal, using Haar eye detection.

    LBPH is sensitive to head tilt; eye-based alignment removes most of that
    variance before the crop is resized and histogrammed. Falls back to the
    unaligned crop when both eyes aren't found (e.g. glasses glare, side pose).
    """
    roi = gray[y:y + h, x:x + w]
    eye_cascade = _get_eye_cascade()
    if eye_cascade is None:
        return roi

    eyes = eye_cascade.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=6, minSize=(w // 8, h // 8))
    if len(eyes) < 2:
        return roi

    (ex1, ey1, ew1, eh1), (ex2, ey2, ew2, eh2) = sorted(eyes, key=lambda e: e[0])[:2]
    left_eye = (ex1 + ew1 / 2, ey1 + eh1 / 2)
    right_eye = (ex2 + ew2 / 2, ey2 + eh2 / 2)
    if left_eye[0] > right_eye[0]:
        left_eye, right_eye = right_eye, left_eye

    angle = np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))
    rotation = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(roi, rotation, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def extract_face(frame):
    """Detect the largest face in a BGR frame and return a normalized grayscale
    crop (aligned to the eye line and lighting-corrected via CLAHE), or None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _get_face_cascade().detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])

    aligned = _align_face(gray, x, y, w, h)
    resized = cv2.resize(aligned, FACE_SIZE)
    return _get_clahe().apply(resized)


def _student_sample_dir(student_id):
    return os.path.join(SAMPLES_DIR, str(student_id))


def _save_student_samples(student_id, face_samples):
    """Replace this student's stored samples with a fresh capture batch, so
    re-enrollment fully supersedes old (possibly stale) captures.
    """
    sample_dir = _student_sample_dir(student_id)
    if os.path.isdir(sample_dir):
        shutil.rmtree(sample_dir)
    os.makedirs(sample_dir, exist_ok=True)
    for i, face in enumerate(face_samples):
        cv2.imwrite(os.path.join(sample_dir, f'{i:03d}.png'), face)


def delete_student_samples(student_id):
    """Remove a student's stored samples (e.g. on student deletion) and retrain
    so the model doesn't keep matching against a removed student.
    """
    sample_dir = _student_sample_dir(student_id)
    if os.path.isdir(sample_dir):
        shutil.rmtree(sample_dir)
    _retrain_from_disk()


def _load_all_samples():
    """Load every stored face sample keyed by student id, for a full retrain."""
    samples, labels = [], []
    if not os.path.isdir(SAMPLES_DIR):
        return samples, labels
    for entry in os.listdir(SAMPLES_DIR):
        student_path = os.path.join(SAMPLES_DIR, entry)
        if not os.path.isdir(student_path) or not entry.isdigit():
            continue
        student_id = int(entry)
        for filename in os.listdir(student_path):
            img = cv2.imread(os.path.join(student_path, filename), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                samples.append(img)
                labels.append(student_id)
    return samples, labels


def _new_recognizer():
    # Tuned for 200x200 CLAHE-normalized, eye-aligned crops: a slightly larger
    # radius and finer grid than the OpenCV defaults (1, 8, 8, 8) capture more
    # local texture detail without overfitting to single-pixel noise.
    return cv2.face.LBPHFaceRecognizer_create(radius=2, neighbors=8, grid_x=10, grid_y=10)


def _retrain_from_disk():
    """Rebuild the shared recognizer from every stored sample on disk.

    A full retrain (rather than an incremental update) keeps the model
    consistent after re-enrollments or deletions, and its cost is negligible
    at attendance-system scale.
    """
    samples, labels = _load_all_samples()
    if not samples:
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        return False

    recognizer = _new_recognizer()
    recognizer.train(samples, np.array(labels))
    os.makedirs(FACE_DATA_DIR, exist_ok=True)
    recognizer.write(MODEL_PATH)
    return True


def enroll_student_face(student_id, face_samples):
    """Persist new face samples for a student and retrain the shared recognizer
    from every stored sample, so the model reflects the full enrolled dataset.
    """
    if not face_samples:
        return False

    os.makedirs(FACE_DATA_DIR, exist_ok=True)
    _save_student_samples(student_id, face_samples)
    return _retrain_from_disk()


_recognizer_cache = {'recognizer': None, 'mtime': None}


def _get_trained_recognizer():
    if not os.path.exists(MODEL_PATH):
        return None
    mtime = os.path.getmtime(MODEL_PATH)
    if _recognizer_cache['recognizer'] is None or _recognizer_cache['mtime'] != mtime:
        recognizer = _new_recognizer()
        recognizer.read(MODEL_PATH)
        _recognizer_cache['recognizer'] = recognizer
        _recognizer_cache['mtime'] = mtime
    return _recognizer_cache['recognizer']


def recognize_face(face):
    """Match a normalized grayscale face crop against enrolled students.

    Returns (student_id, distance) on a confident match, else (None, distance).
    """
    if face is None:
        return None, None
    recognizer = _get_trained_recognizer()
    if recognizer is None:
        return None, None

    student_id, distance = recognizer.predict(face)
    if distance <= MATCH_DISTANCE_THRESHOLD:
        return student_id, distance
    return None, distance
