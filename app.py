import os

from flask import Flask, redirect, send_from_directory, url_for

from extensions import db


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'attendance-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'captured_faces')
app.config['ATTENDANCE_FOLDER'] = os.path.join(os.path.dirname(__file__), 'attendance_records')

# Bind the shared SQLAlchemy extension to this Flask app.
db.init_app(app)

# Ensure folders exist before routes try to save faces or attendance files.
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['ATTENDANCE_FOLDER'], exist_ok=True)

# Import routes after db.init_app(app), so routes and models can safely use db.
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.teacher_routes import teacher_bp
from routes.fingerprint_routes import fp_bp
from routes.attendance_routes import att_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(teacher_bp, url_prefix='/teacher')
app.register_blueprint(fp_bp, url_prefix='/fingerprint')
app.register_blueprint(att_bp, url_prefix='/attendance')


@app.route('/')
def index():
    return redirect(url_for('auth.login'))


@app.route('/captured_faces/<path:filename>')
def captured_face(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/attendance_records/<path:filename>')
def attendance_file(filename):
    return send_from_directory(app.config['ATTENDANCE_FOLDER'], filename)


if __name__ == '__main__':
    from models import create_tables

    with app.app_context():
        create_tables()

    app.run(host='0.0.0.0', port=5000, debug=True)
