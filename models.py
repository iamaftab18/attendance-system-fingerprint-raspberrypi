from datetime import datetime
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class Admin(db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    teachers = db.relationship('Teacher', backref='dept', lazy=True)
    students = db.relationship('Student', backref='dept', lazy=True)


class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=True)
    fingerprint_id = db.Column(db.Integer, unique=True, nullable=True)
    fingerprint_enrolled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lectures = db.relationship('Lecture', backref='teacher', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'employee_id': self.employee_id,
            'department': self.dept.name if self.dept else '',
            'email': self.email,
            'fingerprint_enrolled': self.fingerprint_enrolled
        }


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    prn = db.Column(db.String(50), unique=True, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False, default=1)
    fingerprint_id = db.Column(db.Integer, unique=True, nullable=True)
    fingerprint_enrolled = db.Column(db.Boolean, default=False)
    face_enrolled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('AttendanceRecord', backref='student', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'prn': self.prn,
            'department_id': self.department_id,
            'department': self.dept.name if self.dept else '',
            'year': self.year,
            'fingerprint_enrolled': self.fingerprint_enrolled,
            'face_enrolled': self.face_enrolled
        }


class Lecture(db.Model):
    __tablename__ = 'lectures'
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    lecture_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, active, completed
    excel_path = db.Column(db.String(300), nullable=True)
    teacher_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('AttendanceRecord', backref='lecture', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'subject': self.subject,
            'teacher_name': self.teacher.name if self.teacher else '',
            'department_id': self.department_id,
            'year': self.year,
            'lecture_date': self.lecture_date.strftime('%Y-%m-%d'),
            'start_time': self.start_time,
            'end_time': self.end_time,
            'status': self.status,
            'excel_path': self.excel_path,
            'teacher_verified': self.teacher_verified
        }


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    id = db.Column(db.Integer, primary_key=True)
    lecture_id = db.Column(db.Integer, db.ForeignKey('lectures.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    in_time = db.Column(db.DateTime, nullable=True)
    out_time = db.Column(db.DateTime, nullable=True)
    face_image_path = db.Column(db.String(300), nullable=True)
    failed_attempts = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='absent')  # absent, present, out

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else '',
            'student_prn': self.student.prn if self.student else '',
            'in_time': self.in_time.strftime('%H:%M:%S') if self.in_time else '',
            'out_time': self.out_time.strftime('%H:%M:%S') if self.out_time else '',
            'face_image_path': self.face_image_path,
            'status': self.status
        }


def _ensure_columns():
    """Add columns introduced after the initial db.create_all() run, for existing databases."""
    inspector = db.inspect(db.engine)
    student_columns = [c['name'] for c in inspector.get_columns('students')]
    if 'face_enrolled' not in student_columns:
        db.session.execute(db.text('ALTER TABLE students ADD COLUMN face_enrolled BOOLEAN DEFAULT 0'))
        db.session.commit()


def create_tables():
    db.create_all()
    _ensure_columns()
    # Create default admin if not exists
    if not Admin.query.filter_by(username='admin').first():
        admin = Admin(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)

    # Create default departments
    default_depts = [
        {'name': 'Computer Engineering', 'code': 'CE'},
        {'name': 'Information Technology', 'code': 'IT'},
        {'name': 'Electronics & Telecom', 'code': 'ENTC'},
        {'name': 'Mechanical Engineering', 'code': 'MECH'},
        {'name': 'Civil Engineering', 'code': 'CIVIL'},
    ]
    for dept_data in default_depts:
        if not Department.query.filter_by(code=dept_data['code']).first():
            dept = Department(**dept_data)
            db.session.add(dept)

    db.session.commit()
    print("Database initialized successfully!")
