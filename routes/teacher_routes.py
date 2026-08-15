from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models import Teacher, Student, Department, Lecture, AttendanceRecord
from datetime import datetime, date, timedelta

teacher_bp = Blueprint('teacher', __name__)


def teacher_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'teacher':
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def _parse_lecture_time(value):
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _lecture_window(lecture):
    start = _parse_lecture_time(lecture.start_time)
    end = _parse_lecture_time(lecture.end_time)
    if not start or not end:
        return None, None
    return datetime.combine(lecture.lecture_date, start), datetime.combine(lecture.lecture_date, end)


def _lecture_has_started(lecture, now=None):
    now = now or datetime.now()
    start_dt, _ = _lecture_window(lecture)
    return bool(start_dt and now >= start_dt)


def _lecture_can_accept_attendance(lecture, now=None):
    now = now or datetime.now()
    start_dt, end_dt = _lecture_window(lecture)
    return bool(start_dt and end_dt and start_dt <= now <= end_dt)


def _consume_teacher_fp_verification(lecture):
    verification = session.get('teacher_fp_verified')
    if not verification:
        return False
    try:
        verified_at = datetime.fromisoformat(verification.get('verified_at'))
    except (TypeError, ValueError):
        session.pop('teacher_fp_verified', None)
        return False
    is_valid = (
        verification.get('teacher_id') == session.get('user_id') and
        verification.get('lecture_id') == lecture.id and
        datetime.now() - verified_at <= timedelta(minutes=2)
    )
    if is_valid:
        session.pop('teacher_fp_verified', None)
    return is_valid


@teacher_bp.route('/dashboard')
@teacher_required
def dashboard():
    teacher = Teacher.query.get(session['user_id'])
    lectures = Lecture.query.filter_by(teacher_id=teacher.id).order_by(Lecture.created_at.desc()).limit(10).all()
    active_lecture = Lecture.query.filter_by(teacher_id=teacher.id, status='active').first()
    departments = Department.query.all()
    students = Student.query.order_by(Student.name.asc()).all()
    return render_template('teacher/dashboard.html',
                           teacher=teacher,
                           lectures=[l.to_dict() for l in lectures],
                           active_lecture=active_lecture.to_dict() if active_lecture else None,
                           departments=departments,
                           students=[s.to_dict() for s in students])


@teacher_bp.route('/lectures/create', methods=['POST'])
@teacher_required
def create_lecture():
    data = request.get_json()
    teacher = Teacher.query.get(session['user_id'])
    try:
        lecture = Lecture(
            subject=data['subject'],
            teacher_id=teacher.id,
            department_id=int(data['department_id']),
            year=int(data['year']),
            lecture_date=date.today(),
            start_time=data['start_time'],
            end_time=data['end_time'],
            status='pending'
        )
        db.session.add(lecture)
        db.session.commit()
        return jsonify({'success': True, 'lecture_id': lecture.id, 'message': 'Lecture created. Please verify your fingerprint to start.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@teacher_bp.route('/lectures/<int:lid>/activate', methods=['POST'])
@teacher_required
def activate_lecture(lid):
    lecture = Lecture.query.get_or_404(lid)
    if lecture.teacher_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'})
    if not _lecture_has_started(lecture):
        return jsonify({'success': False, 'message': f'Lecture can start only at {lecture.start_time}'})
    if not _consume_teacher_fp_verification(lecture):
        return jsonify({'success': False, 'message': 'Teacher fingerprint verification required'})
    lecture.status = 'active'
    lecture.teacher_verified = True
    db.session.commit()

    # Create initial Excel file
    from utils.excel_utils import create_lecture_excel
    excel_path = create_lecture_excel(lecture)
    lecture.excel_path = excel_path
    db.session.commit()

    return jsonify({'success': True, 'message': 'Lecture started successfully!'})


@teacher_bp.route('/lectures/<int:lid>/complete', methods=['POST'])
@teacher_required
def complete_lecture(lid):
    lecture = Lecture.query.get_or_404(lid)
    if lecture.teacher_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'})
    if not _consume_teacher_fp_verification(lecture):
        return jsonify({'success': False, 'message': 'Teacher fingerprint verification required to end lecture'})
    lecture.status = 'completed'
    db.session.commit()

    # Save final Excel
    from utils.excel_utils import finalize_lecture_excel
    excel_path = finalize_lecture_excel(lecture)
    lecture.excel_path = excel_path
    db.session.commit()

    return jsonify({'success': True, 'message': 'Lecture completed and attendance saved!'})


@teacher_bp.route('/lectures/<int:lid>/attendance')
@teacher_required
def get_lecture_attendance(lid):
    lecture = Lecture.query.get_or_404(lid)
    records = AttendanceRecord.query.filter_by(lecture_id=lid).all()
    return jsonify({
        'lecture': lecture.to_dict(),
        'attendance': [r.to_dict() for r in records]
    })


@teacher_bp.route('/lectures/<int:lid>/manual_add', methods=['POST'])
@teacher_required
def manual_add_student(lid):
    lecture = Lecture.query.get_or_404(lid)
    if lecture.teacher_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorized'})
    if lecture.status != 'active':
        return jsonify({'success': False, 'message': 'Manual attendance can only be added while lecture is active'})
    data = request.get_json() or {}
    student_id = data.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': 'Student is required'})
    student = Student.query.get(student_id)
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})

    existing = AttendanceRecord.query.filter_by(lecture_id=lecture.id, student_id=student.id).first()
    if existing:
        return jsonify({'success': False, 'message': f'{student.name} is already marked present'})

    try:
        record = AttendanceRecord(
            lecture_id=lecture.id,
            student_id=student.id,
            in_time=datetime.now(),
            status='present'
        )
        db.session.add(record)
        db.session.commit()
        from utils.excel_utils import append_student_to_excel
        append_student_to_excel(lecture, record)
        return jsonify({
            'success': True,
            'message': f'{student.name} added to attendance',
            'attendance': record.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@teacher_bp.route('/students/enroll', methods=['GET'])
@teacher_required
def enroll_students():
    teacher = Teacher.query.get(session['user_id'])
    departments = Department.query.all()
    students = Student.query.order_by(Student.created_at.desc()).all()
    return render_template('teacher/enroll.html',
                           teacher=teacher,
                           departments=departments,
                           students=[s.to_dict() for s in students])


@teacher_bp.route('/students/add', methods=['POST'])
@teacher_required
def add_student():
    data = request.get_json()
    try:
        if Student.query.filter_by(prn=data['prn']).first():
            return jsonify({'success': False, 'message': 'PRN already exists'})
        student = Student(
            name=data['name'],
            prn=data['prn'],
            department_id=int(data['department_id']),
            year=int(data.get('year', 1))
        )
        db.session.add(student)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Student added', 'id': student.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@teacher_bp.route('/lectures/history')
@teacher_required
def lecture_history():
    teacher = Teacher.query.get(session['user_id'])
    lectures = Lecture.query.filter_by(teacher_id=teacher.id).order_by(Lecture.created_at.desc()).all()
    lecture_summaries = []
    for lecture in lectures:
        records = AttendanceRecord.query.filter_by(lecture_id=lecture.id).all()
        department = Department.query.get(lecture.department_id)
        expected_students = Student.query.filter_by(
            department_id=lecture.department_id,
            year=lecture.year
        ).count()
        present_count = sum(1 for record in records if record.status == 'present')
        lecture_data = lecture.to_dict()
        lecture_data.update({
            'department': department.name if department else '',
            'department_code': department.code if department else '',
            'present_count': present_count,
            'out_count': 0,
            'expected_students': expected_students,
            'attendance_rate': round((present_count / expected_students) * 100) if expected_students else 0
        })
        lecture_summaries.append(lecture_data)

    return render_template('teacher/history.html',
                           teacher=teacher,
                           lectures=lecture_summaries)
