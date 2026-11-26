"""Análisis de asistencia basado en reglas configurables."""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import and_, select

from .db import settings
from .models import Alert, Attendance, ClassSession, Enrollment, User, now
from .reporting_time import reporting_date


def risk_policy():
    return {
        'min_sessions': settings.absenteeism_min_sessions,
        'high_below': settings.absenteeism_high_below,
        'medium_below': settings.absenteeism_medium_below,
        'high_streak': settings.absenteeism_high_streak,
        'medium_streak': settings.absenteeism_medium_streak,
    }


def attendance_timelines(db, course_ids=None, student_id=None, *, as_of=None):
    """Return every scoped enrollment, including those with zero eligible sessions."""
    cutoff = as_of if as_of is not None else now()
    query = (
        select(Enrollment, User.name, ClassSession.started_at, Attendance.id)
        .join(User, User.id == Enrollment.student_id)
        .outerjoin(ClassSession, and_(
            ClassSession.course_id == Enrollment.course_id,
            ClassSession.started_at >= Enrollment.created_at,
            ClassSession.closed_at >= ClassSession.started_at,
            ClassSession.closed_at <= cutoff,
        ))
        .outerjoin(Attendance, and_(
            Attendance.session_id == ClassSession.id,
            Attendance.student_id == Enrollment.student_id,
        ))
        .order_by(Enrollment.id, ClassSession.started_at, ClassSession.id)
    )
    if course_ids is not None:
        query = query.where(Enrollment.course_id.in_(course_ids))
    if student_id is not None:
        query = query.where(Enrollment.student_id == student_id)
    timelines = {}
    for enrollment, name, started_at, attendance_id in db.execute(query):
        _, _, history = timelines.setdefault(enrollment.id, (enrollment, name, []))
        if started_at is not None:
            history.append((started_at, int(attendance_id is not None)))
    return timelines.values()


def percentage(count, total):
    return round(count * 100 / total, 1) if total else None


def trailing_absences(flags):
    consecutive = 0
    for present in reversed(flags):
        if present:
            break
        consecutive += 1
    return consecutive


def calculate_risk(history, policy):
    flags = [present for _, present in history]
    total, attended = len(flags), sum(flags)
    consecutive = trailing_absences(flags)
    level, reasons = 'sin_datos', []
    if total >= policy['min_sessions']:
        rate = attended * 100 / total
        level = 'bajo'
        for candidate, threshold in [('alto', 'high'), ('medio', 'medium')]:
            below, streak = policy[f'{threshold}_below'], policy[f'{threshold}_streak']
            if rate < below:
                reasons.append(f'Asistencia inferior al {below:g}%')
            if consecutive >= streak:
                reasons.append(f'Racha activa de al menos {streak} ausencias')
            if reasons:
                level = candidate
                break
    return {
        'total': total, 'present': attended, 'absent': total - attended,
        'rate': percentage(attended, total), 'consecutive': consecutive,
        'level': level, 'reasons': reasons, 'recent': flags[-5:],
    }


def student_stats(db, enrollment):
    for candidate, _, history in attendance_timelines(db, [enrollment.course_id], enrollment.student_id):
        if candidate.id == enrollment.id:
            return calculate_risk(history, risk_policy())
    return calculate_risk([], risk_policy())


def refresh_alerts(db, course_id):
    existing = {a.student_id: a for a in db.scalars(select(Alert).where(Alert.course_id == course_id))}
    policy = risk_policy()
    for enrollment, _, history in attendance_timelines(db, [course_id]):
        stats = calculate_risk(history, policy)
        alert = existing.pop(enrollment.student_id, None)
        if stats['level'] in ('medio', 'alto'):
            if alert is None:
                alert = Alert(student_id=enrollment.student_id, course_id=course_id)
                db.add(alert)
            alert.level = stats['level']
            alert.message = '. '.join(stats['reasons'])
        elif alert is not None:
            db.delete(alert)
    for alert in existing.values():
        db.delete(alert)


def attendance_overview(db, courses, student_id, as_of):
    policy = risk_policy()
    today = reporting_date(as_of)
    days = {}
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        days[day] = {'date': day.isoformat(), 'present': 0, 'expected': 0}

    names = {course.id: course.name for course in courses}
    course_counts = {course_id: [0, 0] for course_id in names}
    student_counts = defaultdict(lambda: [0, 0])
    student_names = {}
    items = []
    for enrollment, name, history in attendance_timelines(db, list(names), student_id, as_of=as_of):
        stats = calculate_risk(history, policy)
        items.append({'id': enrollment.id, 'student': name, 'course': names[enrollment.course_id], **stats})
        student_names[enrollment.student_id] = name
        for counts in (course_counts[enrollment.course_id], student_counts[enrollment.student_id]):
            counts[0] += stats['present']
            counts[1] += stats['total']
        for timestamp, present in history:
            day = days.get(reporting_date(timestamp))
            if day is not None:
                day['expected'] += 1
                day['present'] += present

    def ranking(counts, labels):
        rows = [(key, present, total) for key, (present, total) in counts.items() if total > present]
        rows.sort(key=lambda row: (-(row[2] - row[1]) / row[2], -(row[2] - row[1]), labels[row[0]], row[0]))
        return [{'id': key, 'name': labels[key], 'absent': total - present,
                 'expected': total, 'rate': percentage(total - present, total)}
                for key, present, total in rows[:5]]

    daily = list(days.values())

    def period(rows):
        present = sum(row['present'] for row in rows)
        expected = sum(row['expected'] for row in rows)
        return {'start': rows[0]['date'], 'end': rows[-1]['date'],
                'present': present, 'expected': expected, 'rate': percentage(present, expected)}

    previous, current = period(daily[:7]), period(daily[7:])
    change = None
    if previous['expected'] and current['expected']:
        change = round(100 * (current['present'] / current['expected']
                              - previous['present'] / previous['expected']), 1)

    return {
        'students': len(student_counts),
        'students_stats': items,
        'alerts': sorted((item for item in items if item['level'] in ('medio', 'alto')),
                         key=lambda item: (item['level'] != 'alto', -item['consecutive'], item['rate'])),
        'week': daily[7:],
        'courses': [{'name': names[key], 'present': present, 'expected': total,
                     'rate': percentage(present, total)}
                    for key, (present, total) in course_counts.items()],
        'absenteeism': {
            'policy': policy,
            'trend': {'previous': previous, 'current': current, 'change': change},
            'top_students': ranking(student_counts, student_names) if student_id is None else [],
            'top_courses': ranking(course_counts, names),
        },
    }


def experimental_model(rows):
    """Solo entrenamiento real con etiquetas históricas; nunca inventa resultados."""
    if len(rows) < 100 or len(set(r['next_absent'] for r in rows)) < 2:
        return {'status': 'insufficient_data', 'message': 'Se requieren 100 ventanas históricas etiquetadas y ambas clases. Se utilizan reglas estadísticas.'}
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import balanced_accuracy_score
    x = [r['features'] for r in rows]
    y = [r['next_absent'] for r in rows]
    # Orden temporal; evita entrenar con el futuro.
    train_x, test_x, train_y, test_y = train_test_split(x, y, test_size=.25, shuffle=False)
    if len(set(train_y)) < 2 or len(set(test_y)) < 2:
        return {'status': 'insufficient_data', 'message': 'Faltan ambas clases en la separación temporal.'}
    model = LogisticRegression(class_weight='balanced', random_state=42).fit(train_x, train_y)
    return {'status': 'experimental', 'samples': len(rows), 'balanced_accuracy': float(balanced_accuracy_score(test_y, model.predict(test_x))), 'message': 'Evaluación histórica experimental; no es un diagnóstico académico.'}
