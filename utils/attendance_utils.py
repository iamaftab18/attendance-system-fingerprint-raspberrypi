import os
from datetime import datetime, timedelta

from extensions import db
from models import Student, Lecture, AttendanceRecord
from utils.mail_utils import send_email

ATTENDANCE_THRESHOLD = float(os.environ.get('ATTENDANCE_THRESHOLD', 75))
CHECK_INTERVAL_DAYS = int(os.environ.get('ATTENDANCE_CHECK_INTERVAL_DAYS', 30))


def calculate_attendance(student, since=None, until=None):
    """Percentage of a student's own department/year lectures they attended.

    Returns (percentage, present_count, total_count). percentage is None when
    there are no completed lectures in the window, since a percentage isn't
    meaningful yet.
    """
    query = Lecture.query.filter_by(
        department_id=student.department_id,
        year=student.year,
        status='completed'
    )
    if since is not None:
        query = query.filter(Lecture.lecture_date >= since)
    if until is not None:
        query = query.filter(Lecture.lecture_date <= until)
    lecture_ids = [l.id for l in query.all()]

    total = len(lecture_ids)
    if total == 0:
        return None, 0, 0

    present = AttendanceRecord.query.filter(
        AttendanceRecord.student_id == student.id,
        AttendanceRecord.lecture_id.in_(lecture_ids),
        AttendanceRecord.status == 'present'
    ).count()

    percentage = round((present / total) * 100, 1)
    return percentage, present, total


def average_attendance_percentage(students, since=None, until=None):
    """Average attendance percentage across a list of students, ignoring
    students with no completed lectures yet. Returns None if none qualify."""
    percentages = []
    for student in students:
        percentage, _, _ = calculate_attendance(student, since=since, until=until)
        if percentage is not None:
            percentages.append(percentage)
    if not percentages:
        return None
    return round(sum(percentages) / len(percentages), 1)


def run_low_attendance_check(force=False):
    """Re-check each student whose attendance window has elapsed and email
    the parent if attendance over the trailing window is below the
    configured threshold. Must be called inside an app context.
    """
    now = datetime.utcnow()
    window_start = (now - timedelta(days=CHECK_INTERVAL_DAYS)).date()
    window_end = now.date()

    summary = {'checked': 0, 'flagged': 0, 'emailed': 0, 'skipped_no_email': 0, 'errors': []}

    for student in Student.query.all():
        due = (
            force or
            student.last_attendance_check is None or
            (now - student.last_attendance_check) >= timedelta(days=CHECK_INTERVAL_DAYS)
        )
        if not due:
            continue

        summary['checked'] += 1
        percentage, present, total = calculate_attendance(student, since=window_start, until=window_end)
        student.last_attendance_check = now

        if percentage is not None and percentage < ATTENDANCE_THRESHOLD:
            summary['flagged'] += 1
            if student.parent_email:
                subject = f'Attendance Alert: {student.name} ({student.prn})'
                body = (
                    f'Dear Parent/Guardian,\n\n'
                    f'This is to inform you that {student.name} (PRN: {student.prn}) has an attendance of '
                    f'{percentage}% ({present}/{total} lectures) over the last {CHECK_INTERVAL_DAYS} days, '
                    f'which is below the required minimum of {ATTENDANCE_THRESHOLD}%.\n\n'
                    f'Please ensure regular attendance going forward. Contact the department office for more details.\n\n'
                    f'Regards,\nAttendance Office'
                )
                sent, error = send_email(subject, [student.parent_email], body)
                if sent:
                    summary['emailed'] += 1
                else:
                    summary['errors'].append(f'{student.name}: {error}')
            else:
                summary['skipped_no_email'] += 1

    db.session.commit()
    return summary


def send_absence_notifications(lecture):
    """Email the parents of every student expected in this lecture's
    department/year who was not marked present. Must be called inside an
    app context.
    """
    expected_students = Student.query.filter_by(
        department_id=lecture.department_id,
        year=lecture.year
    ).all()
    present_ids = {
        r.student_id for r in AttendanceRecord.query.filter_by(
            lecture_id=lecture.id, status='present'
        ).all()
    }

    summary = {'absent': 0, 'emailed': 0, 'skipped_no_email': 0, 'errors': []}

    for student in expected_students:
        if student.id in present_ids:
            continue
        summary['absent'] += 1
        if not student.parent_email:
            summary['skipped_no_email'] += 1
            continue

        subject = f'Absence Alert: {student.name} ({lecture.subject})'
        body = (
            f'Dear Parent/Guardian,\n\n'
            f"This is to inform you that {student.name} (PRN: {student.prn}) was marked absent for "
            f'the following lecture:\n\n'
            f'  Subject: {lecture.subject}\n'
            f'  Date: {lecture.lecture_date.strftime("%d %b %Y")}\n'
            f'  Time: {lecture.start_time} - {lecture.end_time}\n\n'
            f'Regards,\nAttendance Office'
        )
        sent, error = send_email(subject, [student.parent_email], body)
        if sent:
            summary['emailed'] += 1
        else:
            summary['errors'].append(f'{student.name}: {error}')

    return summary
