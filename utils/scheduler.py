import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

CHECK_LOOP_SECONDS = 24 * 60 * 60  # re-evaluate which students are due once a day


def _loop(app):
    from utils.attendance_utils import run_low_attendance_check

    while True:
        try:
            with app.app_context():
                summary = run_low_attendance_check()
                if summary['checked']:
                    logger.info('Attendance check run: %s', summary)
        except Exception:
            logger.exception('Attendance scheduler run failed')
        time.sleep(CHECK_LOOP_SECONDS)


def start_attendance_scheduler(app):
    """Start the daily background thread that emails parents of students
    whose trailing attendance has fallen below the threshold.

    Guarded against Flask's debug reloader, which forks a watcher process
    before the real server process - only the process actually serving
    requests (WERKZEUG_RUN_MAIN=true) should run the loop, otherwise it
    would run twice and could double-send emails.
    """
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
    thread = threading.Thread(target=_loop, args=(app,), daemon=True)
    thread.start()
