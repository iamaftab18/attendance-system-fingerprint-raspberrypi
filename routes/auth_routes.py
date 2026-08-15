from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models import Admin, Teacher

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    data = request.get_json()
    role = data.get('role')
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if role == 'admin':
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session['user_id'] = admin.id
            session['role'] = 'admin'
            session['name'] = 'Administrator'
            return jsonify({'success': True, 'redirect': '/admin/dashboard'})
        return jsonify({'success': False, 'message': 'Invalid admin credentials'})

    elif role == 'teacher':
        teacher = Teacher.query.filter_by(email=username).first()
        if not teacher:
            return jsonify({'success': False, 'message': 'Teacher email not found'})
        if not teacher.fingerprint_enrolled:
            return jsonify({'success': False, 'message': 'Teacher fingerprint is not registered. Please ask admin to add fingerprint.'})
        return jsonify({'success': False, 'message': 'Fingerprint verification required', 'requires_fingerprint': True, 'teacher_id': teacher.id})

    return jsonify({'success': False, 'message': 'Invalid role'})


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


def login_required(role=None):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if role and session.get('role') != role:
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
