import os
import sys
import threading

import cv2

PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 480

# If this many consecutive reads fail while a handle is supposedly open, the
# device has likely gone stale (driver reset, USB power-save, left idle too
# long) - close and reopen it rather than failing forever on a dead handle.
MAX_CONSECUTIVE_READ_FAILURES = 5


def _camera_indices_to_try():
    """CAMERA_INDEX lets a device pin the exact /dev/videoN it wants (mirrors
    FINGERPRINT_PORT for the sensor). Otherwise probe the first few indices,
    since USB webcams don't always land on 0.
    """
    override = os.environ.get('CAMERA_INDEX')
    if override is not None:
        try:
            return [int(override)]
        except ValueError:
            print(f'[Camera] Ignoring invalid CAMERA_INDEX={override!r}')
    return [0, 1, 2]


class CameraManager:
    """A single, reference-counted VideoCapture handle shared by every camera
    consumer in the app (the live preview stream and one-shot capture calls).

    Most V4L2 webcams only allow one open handle at a time, so a live preview
    and an in-progress face capture can't each open their own - they take
    turns reading from this one shared handle instead, serialized by a lock.
    The device is opened on first use and released once every consumer has
    called release().
    """

    def __init__(self):
        self._cap = None
        self._lock = threading.Lock()
        self._refcount = 0
        self._consecutive_failures = 0

    def _open(self):
        backend = cv2.CAP_V4L2 if sys.platform.startswith('linux') else cv2.CAP_ANY
        tried = _camera_indices_to_try()
        for index in tried:
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, PREVIEW_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, PREVIEW_HEIGHT)
                return cap
            cap.release()

        print(f'[Camera] Unable to open camera for capture. Tried index(es) {tried}. '
              f'Run `ls /dev/video*` to confirm a device exists, or set CAMERA_INDEX '
              f'to the right one.')
        return None

    def acquire(self):
        """Open the camera if needed and register a consumer. Returns False if
        the camera couldn't be opened. Always pair with release()."""
        with self._lock:
            if self._cap is None:
                self._cap = self._open()
                if self._cap is None:
                    return False
                self._consecutive_failures = 0
            self._refcount += 1
            return True

    def release(self):
        with self._lock:
            if self._refcount > 0:
                self._refcount -= 1
            if self._refcount == 0 and self._cap is not None:
                self._cap.release()
                self._cap = None
                self._consecutive_failures = 0

    def read_frame(self):
        """Read the next frame. Must only be called between acquire()/release().

        If the device starts failing reads repeatedly while still "open" (a
        real V4L2 failure mode - driver reset, USB suspend, a handle left idle
        too long by an abandoned preview connection), transparently close and
        reopen it instead of returning None forever.
        """
        with self._lock:
            if self._cap is None:
                return None
            ret, frame = self._cap.read()
            if not ret or frame is None:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    print(f'[Camera] {self._consecutive_failures} consecutive failed reads - '
                          f'the device looks stale, reopening it.')
                    self._cap.release()
                    self._cap = self._open()
                    self._consecutive_failures = 0
                return None
            self._consecutive_failures = 0
            return frame

    def force_reset(self):
        """Drop the handle and refcount unconditionally - an escape hatch for
        a camera that's stuck regardless of the self-healing above."""
        with self._lock:
            if self._cap is not None:
                self._cap.release()
            self._cap = None
            self._refcount = 0
            self._consecutive_failures = 0


camera_manager = CameraManager()
