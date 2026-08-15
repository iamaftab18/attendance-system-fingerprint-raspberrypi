from flask import Blueprint, request, jsonify, session, redirect, url_for
from extensions import db
from models import Lecture, AttendanceRecord, Student

att_bp = Blueprint('attendance', __name__)


@att_bp.route('/lecture/<int:lid>')
def lecture_attendance(lid):
    records = AttendanceRecord.query.filter_by(lecture_id=lid).all()
    lecture = Lecture.query.get_or_404(lid)
    record_list = [r.to_dict() for r in records]
    return jsonify({
        'lecture': lecture.to_dict(),
        'records': record_list,
        'attendance': record_list,
        'present_count': sum(1 for r in records if r.status == 'present'),
        'total': len(records)
    })
