from flask import Blueprint, request, jsonify, session, current_app, Response
from extensions import db
from models import Teacher, Student, Lecture, AttendanceRecord
from datetime import datetime
from routes.teacher_routes import _lecture_can_accept_attendance
from utils.r307s_sensor import connect_r307s
from utils.camera import camera_manager
import os
import time

fp_bp = Blueprint('fingerprint', __name__)

# Global state for fingerprint operations
fp_state = {
    'sensor': None,
    'available': False,
    'port': None,
    'diagnostics': [],
    'failed_attempts': {}  # key: (lecture_id, context) -> count
}

def get_sensor():
    """Initialize an R307S fingerprint sensor on Raspberry Pi serial ports."""
    if fp_state['sensor'] is not None:
        return fp_state['sensor']

    sensor, port, diagnostics = connect_r307s()
    fp_state['diagnostics'] = diagnostics
    fp_state['port'] = port

    if sensor:
        fp_state['sensor'] = sensor
        fp_state['available'] = True
        print(f"[Fingerprint] R307S connected on {port}")
        return sensor

    fp_state['available'] = False
    print("[Fingerprint] R307S sensor not available:")
    for line in diagnostics:
        print(f"  - {line}")
    return None


def _grab_camera_frame():
    """Grab a single frame from the shared camera."""
    if not camera_manager.acquire():
        return None
    try:
        frame = camera_manager.read_frame()
        if frame is None:
            print('[Camera] Failed to read frame from camera.')
        return frame
    finally:
        camera_manager.release()


def _grab_camera_frames(count, delay=0.25):
    """Grab several frames from the shared camera, e.g. for face enrollment.

    Uses the same reference-counted handle as the live preview stream, so
    enrollment capture can run while a preview is still connected instead of
    fighting it for exclusive access to the device.
    """
    if not camera_manager.acquire():
        return []
    try:
        frames = []
        for _ in range(count):
            frame = camera_manager.read_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(delay)
        return frames
    finally:
        camera_manager.release()


@fp_bp.route('/camera/preview')
def camera_preview():
    """MJPEG live preview so a student/teacher can frame themselves before
    (and during) face capture. Shares the camera with capture via camera_manager
    instead of taking exclusive ownership of it.
    """
    import cv2

    def generate():
        if not camera_manager.acquire():
            return
        try:
            while True:
                frame = camera_manager.read_frame()
                if frame is not None:
                    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.08)
        finally:
            camera_manager.release()

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


def _save_evidence_frame(frame, context_label):
    """Save a raw captured frame as an unauthorized-attempt record."""
    try:
        import cv2
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"unauthorized_{context_label}_{timestamp}.jpg"
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
        save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        cv2.imwrite(save_path, frame)
        return filename
    except Exception as e:
        print(f"[Camera] Failed to save evidence frame: {e}")
        return None


def capture_face_on_failure(lecture_id, context_label):
    """Capture image from USB webcam after 3 failed fingerprint attempts."""
    frame = _grab_camera_frame()
    if frame is None:
        return None
    return _save_evidence_frame(frame, context_label)


def attempt_face_attendance(context_label):
    """After repeated fingerprint failures, try to recognize the student's face
    from the webcam so attendance can be marked directly. Falls back to saving
    an evidence photo when no face is recognized.
    """
    from utils.face_recognizer import extract_face, recognize_face

    frame = _grab_camera_frame()
    if frame is None:
        return {'status': 'no_camera', 'image': None}

    try:
        face = extract_face(frame)
    except RuntimeError as e:
        print(f'[FaceRecognizer] {e}')
        return {'status': 'detector_error', 'image': _save_evidence_frame(frame, context_label), 'message': str(e)}

    if face is None:
        return {'status': 'no_face', 'image': _save_evidence_frame(frame, context_label)}

    student_id, distance = recognize_face(face)
    student = Student.query.get(student_id) if student_id is not None else None
    if not student:
        return {'status': 'unmatched', 'image': _save_evidence_frame(frame, context_label)}

    return {'status': 'matched', 'student': student, 'distance': distance}


# ── Enroll Fingerprint ────────────────────────────────────────────────────

@fp_bp.route('/enroll/start', methods=['POST'])
def enroll_start():
    data = request.get_json()
    entity_type = data.get('type')  # 'teacher' or 'student'
    entity_id = int(data.get('id'))

    sensor = get_sensor()
    if not sensor:
        # Development mode: allow the UI to continue to the completion step.
        return jsonify({
            'success': True,
            'step': 1,
            'message': '[SIMULATION] First scan accepted because no sensor is connected.',
            'simulated': True
        })

    try:
        # Step 1: First scan
        print('[FP] Waiting for first finger placement...')
        while not sensor.readImage():
            time.sleep(0.1)
        sensor.convertImage(0x01)
        position1 = sensor.searchTemplate()
        if position1[0] >= 0:
            return jsonify({'success': False, 'message': 'Fingerprint already enrolled! Remove finger and try again.'})

        while sensor.readImage():
            time.sleep(0.1)

        return jsonify({'success': True, 'step': 1, 'message': 'First scan complete. Remove finger.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Sensor error: {str(e)}'})


@fp_bp.route('/enroll/complete', methods=['POST'])
def enroll_complete():
    data = request.get_json()
    entity_type = data.get('type')
    entity_id = int(data.get('id'))

    sensor = get_sensor()
    if not sensor:
        # Dev simulation: assign mock fingerprint ID
        if entity_type == 'teacher':
            entity = Teacher.query.get(entity_id)
        else:
            entity = Student.query.get(entity_id)
        if entity:
            mock_id = entity_id + 100
            entity.fingerprint_id = mock_id
            entity.fingerprint_enrolled = True
            db.session.commit()
        return jsonify({'success': True, 'message': '[SIMULATION] Fingerprint enrolled (no hardware)', 'simulated': True})

    try:
        print('[FP] Waiting for second finger placement...')
        while not sensor.readImage():
            time.sleep(0.1)
        sensor.convertImage(0x02)
        if sensor.compareCharacteristics() == 0:
            return jsonify({'success': False, 'message': 'Fingerprint scans did not match. Try again.'})
        sensor.createTemplate()

        # Find free position in sensor
        position = sensor.storeTemplate()
        print(f'[FP] Template stored at position #{position}')

        # Save to DB
        if entity_type == 'teacher':
            entity = Teacher.query.get(entity_id)
        else:
            entity = Student.query.get(entity_id)

        if entity:
            entity.fingerprint_id = position
            entity.fingerprint_enrolled = True
            db.session.commit()
            return jsonify({'success': True, 'message': f'Fingerprint enrolled at slot #{position}', 'position': position})
        return jsonify({'success': False, 'message': 'Entity not found'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Enrollment failed: {str(e)}'})


# ── Enroll Face (fallback identification when fingerprint scanning fails) ─

@fp_bp.route('/face/enroll', methods=['POST'])
def enroll_face():
    from utils.face_recognizer import extract_face, enroll_student_face, SAMPLES_PER_ENROLLMENT

    data = request.get_json()
    student_id = int(data.get('id'))
    student = Student.query.get(student_id)
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})

    frames = _grab_camera_frames(SAMPLES_PER_ENROLLMENT * 3, delay=0.2)
    if not frames:
        return jsonify({'success': False, 'message': 'Camera not available. Check the USB webcam connection.'})

    try:
        samples = []
        for frame in frames:
            face = extract_face(frame)
            if face is not None:
                samples.append(face)
            if len(samples) >= SAMPLES_PER_ENROLLMENT:
                break
    except RuntimeError as e:
        print(f'[FaceRecognizer] {e}')
        return jsonify({'success': False, 'message': f'Face detector is not set up correctly on this device: {e}'})

    min_samples = max(5, SAMPLES_PER_ENROLLMENT // 2)
    if len(samples) < min_samples:
        return jsonify({'success': False, 'message': f'Only captured {len(samples)} clear frame(s) (need {min_samples}+). Sit facing the camera in good lighting and try again.'})

    enroll_student_face(student.id, samples)
    student.face_enrolled = True
    db.session.commit()
    return jsonify({'success': True, 'message': f'Face enrolled for {student.name} ({len(samples)} samples captured, model retrained)'})


# ── Verify Teacher Fingerprint ─────────────────────────────────────────────

@fp_bp.route('/verify/teacher', methods=['POST'])
def verify_teacher():
    data = request.get_json()
    teacher_id = int(data.get('teacher_id'))
    lecture_id = int(data.get('lecture_id'))
    teacher = Teacher.query.get(teacher_id)

    if not teacher or not teacher.fingerprint_enrolled:
        return jsonify({'success': False, 'message': 'Teacher fingerprint not enrolled'})

    sensor = get_sensor()
    if not sensor:
        # Simulate success for dev
        session['teacher_fp_verified'] = {
            'teacher_id': teacher.id,
            'lecture_id': lecture_id,
            'verified_at': datetime.now().isoformat()
        }
        return jsonify({'success': True, 'message': '[SIMULATION] Teacher verified', 'simulated': True})

    attempt_key = f"teacher_{teacher_id}_{lecture_id}"
    try:
        while not sensor.readImage():
            time.sleep(0.1)
        sensor.convertImage(0x01)
        result = sensor.searchTemplate()
        position, accuracy = result

        if position == teacher.fingerprint_id and accuracy > 50:
            fp_state['failed_attempts'][attempt_key] = 0
            session['teacher_fp_verified'] = {
                'teacher_id': teacher.id,
                'lecture_id': lecture_id,
                'verified_at': datetime.now().isoformat()
            }
            return jsonify({'success': True, 'message': 'Teacher identity verified!', 'accuracy': accuracy})
        else:
            count = fp_state['failed_attempts'].get(attempt_key, 0) + 1
            fp_state['failed_attempts'][attempt_key] = count
            if count >= 3:
                fp_state['failed_attempts'][attempt_key] = 0
                img_file = capture_face_on_failure(lecture_id, f'teacher_{teacher_id}')
                return jsonify({
                    'success': False,
                    'message': 'Too many failed attempts. Camera capture attempted.',
                    'camera_triggered': bool(img_file),
                    'image': img_file
                })
            return jsonify({'success': False, 'message': f'Fingerprint not matched. Attempt {count}/3'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ── Student Attendance via Fingerprint ────────────────────────────────────

@fp_bp.route('/login/teacher', methods=['POST'])
def login_teacher_with_fingerprint():
    data = request.get_json()
    email = data.get('email', '').strip()
    teacher = Teacher.query.filter_by(email=email).first()

    if not teacher:
        return jsonify({'success': False, 'message': 'Teacher email not found'})
    if not teacher.fingerprint_enrolled:
        return jsonify({'success': False, 'message': 'Teacher fingerprint is not registered. Please ask admin to add fingerprint.'})

    sensor = get_sensor()
    if not sensor:
        session['user_id'] = teacher.id
        session['role'] = 'teacher'
        session['name'] = teacher.name
        return jsonify({'success': True, 'redirect': '/teacher/dashboard', 'message': '[SIMULATION] Teacher fingerprint verified', 'simulated': True})

    attempt_key = f"teacher_login_{teacher.id}"
    try:
        while not sensor.readImage():
            time.sleep(0.1)
        sensor.convertImage(0x01)
        position, accuracy = sensor.searchTemplate()

        if position == teacher.fingerprint_id and accuracy > 50:
            fp_state['failed_attempts'][attempt_key] = 0
            session['user_id'] = teacher.id
            session['role'] = 'teacher'
            session['name'] = teacher.name
            return jsonify({'success': True, 'redirect': '/teacher/dashboard', 'message': 'Teacher fingerprint verified', 'accuracy': accuracy})

        count = fp_state['failed_attempts'].get(attempt_key, 0) + 1
        fp_state['failed_attempts'][attempt_key] = count
        if count >= 3:
            fp_state['failed_attempts'][attempt_key] = 0
            img_file = capture_face_on_failure(0, f'teacher_login_{teacher.id}')
            return jsonify({'success': False, 'message': 'Too many failed attempts. Camera captured.', 'camera_triggered': True, 'image': img_file})
        return jsonify({'success': False, 'message': f'Fingerprint not matched. Attempt {count}/3'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@fp_bp.route('/scan/student', methods=['POST'])
def scan_student():
    data = request.get_json()
    lecture_id = int(data.get('lecture_id'))
    mode = 'in'

    lecture = Lecture.query.get(lecture_id)
    if not lecture or lecture.status != 'active':
        return jsonify({'success': False, 'message': 'Lecture is not active'})
    if not _lecture_can_accept_attendance(lecture):
        return jsonify({'success': False, 'message': f'Attendance is allowed only during lecture time ({lecture.start_time} - {lecture.end_time})'})

    sensor = get_sensor()
    attempt_key = f"student_scan_{lecture_id}"

    if not sensor:
        # Simulation mode: return mock student
        students_in_dept = Student.query.filter_by(
            department_id=lecture.department_id,
            year=lecture.year,
            fingerprint_enrolled=True
        ).all()
        if not students_in_dept:
            return jsonify({'success': False, 'message': '[SIM] No enrolled students in this lecture'})
        import random
        mock_student = random.choice(students_in_dept)
        return _record_attendance(mock_student, lecture, mode, simulated=True)

    try:
        while not sensor.readImage():
            time.sleep(0.1)
        sensor.convertImage(0x01)
        result = sensor.searchTemplate()
        position, accuracy = result

        if position < 0 or accuracy < 50:
            count = fp_state['failed_attempts'].get(attempt_key, 0) + 1
            fp_state['failed_attempts'][attempt_key] = count
            if count >= 3:
                fp_state['failed_attempts'][attempt_key] = 0
                face_result = attempt_face_attendance('unknown_student')
                if face_result['status'] == 'matched':
                    return _record_attendance(face_result['student'], lecture, mode, via_face=True)
                return jsonify({
                    'success': False,
                    'message': 'Fingerprint failed 3 times and the face was not recognized. Camera capture attempted.',
                    'camera_triggered': True,
                    'image': face_result.get('image')
                })
            return jsonify({'success': False, 'message': f'Fingerprint not recognized. Attempt {count}/3', 'attempts': count})

        # Find student by fingerprint position
        student = Student.query.filter_by(fingerprint_id=position).first()
        if not student:
            return jsonify({'success': False, 'message': 'Student not found in database'})

        fp_state['failed_attempts'][attempt_key] = 0
        return _record_attendance(student, lecture, mode)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


def _record_attendance(student, lecture, mode, simulated=False, via_face=False):
    from utils.excel_utils import append_student_to_excel

    record = AttendanceRecord.query.filter_by(
        lecture_id=lecture.id, student_id=student.id
    ).first()
    if record:
        return jsonify({'success': False, 'message': f'{student.name} already marked present'})

    record = AttendanceRecord(
        lecture_id=lecture.id,
        student_id=student.id,
        in_time=datetime.now(),
        status='present'
    )
    db.session.add(record)
    db.session.commit()
    append_student_to_excel(lecture, record)
    message = f'{student.name} marked present'
    if via_face:
        message += ' (recognized by face after fingerprint failure)'
    return jsonify({
        'success': True,
        'message': message,
        'student': student.to_dict(),
        'in_time': record.in_time.strftime('%H:%M:%S'),
        'simulated': simulated,
        'via_face': via_face
    })



@fp_bp.route('/status')
def sensor_status():
    sensor = get_sensor()
    if sensor:
        try:
            count = sensor.getTemplateCount()
            capacity = sensor.getStorageCapacity()
            return jsonify({
                'available': True,
                'port': fp_state.get('port'),
                'templates': count,
                'capacity': capacity,
                'diagnostics': fp_state.get('diagnostics', [])
            })
        except Exception as e:
            fp_state['sensor'] = None
            fp_state['available'] = False
            return jsonify({
                'available': False,
                'message': f'Sensor was detected but status read failed: {e}',
                'port': fp_state.get('port'),
                'diagnostics': fp_state.get('diagnostics', [])
            })
    return jsonify({
        'available': False,
        'message': 'R307S sensor not connected. Set FINGERPRINT_PORT or check Raspberry Pi serial wiring.',
        'diagnostics': fp_state.get('diagnostics', [])
    })
