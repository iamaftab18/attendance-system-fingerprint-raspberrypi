from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models import Teacher, Student, Department
import secrets

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    teachers = Teacher.query.count()
    students = Student.query.count()
    departments = Department.query.all()
    return render_template('admin/dashboard.html',
                           teacher_count=teachers,
                           student_count=students,
                           departments=departments,
                           admin_name=session.get('name', 'Admin'))


# ── Teachers ────────────────────────────────────────────────────────────────

@admin_bp.route('/teachers')
@admin_required
def teachers():
    all_teachers = Teacher.query.all()
    departments = Department.query.all()
    return render_template('admin/teachers.html',
                           teachers=[t.to_dict() for t in all_teachers],
                           departments=departments,
                           admin_name=session.get('name', 'Admin'))


@admin_bp.route('/teachers/add', methods=['POST'])
@admin_required
def add_teacher():
    data = request.get_json()
    try:
        if Teacher.query.filter_by(email=data['email']).first():
            return jsonify({'success': False, 'message': 'Email already exists'})
        if Teacher.query.filter_by(employee_id=data['employee_id']).first():
            return jsonify({'success': False, 'message': 'Employee ID already exists'})

        teacher = Teacher(
            name=data['name'],
            employee_id=data['employee_id'],
            department_id=int(data['department_id']),
            email=data['email']
        )
        teacher.set_password(secrets.token_urlsafe(32))
        db.session.add(teacher)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Teacher added successfully. Enroll fingerprint before login.', 'id': teacher.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/teachers/<int:tid>', methods=['DELETE'])
@admin_required
def delete_teacher(tid):
    teacher = Teacher.query.get_or_404(tid)
    db.session.delete(teacher)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/teachers/<int:tid>', methods=['PUT'])
@admin_required
def update_teacher(tid):
    teacher = Teacher.query.get_or_404(tid)
    data = request.get_json()
    try:
        teacher.name = data.get('name', teacher.name)
        teacher.employee_id = data.get('employee_id', teacher.employee_id)
        teacher.department_id = int(data.get('department_id', teacher.department_id))
        teacher.email = data.get('email', teacher.email)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Teacher updated'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


# ── Students ────────────────────────────────────────────────────────────────

@admin_bp.route('/students')
@admin_required
def students():
    all_students = Student.query.all()
    departments = Department.query.all()
    return render_template('admin/students.html',
                           students=[s.to_dict() for s in all_students],
                           departments=departments,
                           admin_name=session.get('name', 'Admin'))


@admin_bp.route('/students/add', methods=['POST'])
@admin_required
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
        return jsonify({'success': True, 'message': 'Student added successfully', 'id': student.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/students/<int:sid>', methods=['DELETE'])
@admin_required
def delete_student(sid):
    from utils.face_recognizer import delete_student_samples

    student = Student.query.get_or_404(sid)
    db.session.delete(student)
    db.session.commit()
    delete_student_samples(sid)
    return jsonify({'success': True})


@admin_bp.route('/students/<int:sid>', methods=['PUT'])
@admin_required
def update_student(sid):
    student = Student.query.get_or_404(sid)
    data = request.get_json()
    try:
        student.name = data.get('name', student.name)
        student.prn = data.get('prn', student.prn)
        student.department_id = int(data.get('department_id', student.department_id))
        student.year = int(data.get('year', student.year))
        db.session.commit()
        return jsonify({'success': True, 'message': 'Student updated'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


# ── Departments ──────────────────────────────────────────────────────────────

@admin_bp.route('/departments', methods=['GET'])
@admin_required
def get_departments():
    depts = Department.query.all()
    return jsonify([{'id': d.id, 'name': d.name, 'code': d.code} for d in depts])


@admin_bp.route('/departments/add', methods=['POST'])
@admin_required
def add_department():
    data = request.get_json()
    try:
        dept = Department(name=data['name'], code=data['code'].upper())
        db.session.add(dept)
        db.session.commit()
        return jsonify({'success': True, 'id': dept.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})
