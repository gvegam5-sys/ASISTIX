"""Reglas explicables: solo sesiones cerradas posteriores a la matrícula."""
from sqlalchemy import select
from .models import Enrollment, ClassSession, Attendance, Alert


def student_stats(db, enrollment):
    sessions = db.scalars(select(ClassSession).where(ClassSession.course_id == enrollment.course_id, ClassSession.closed_at.is_not(None), ClassSession.started_at >= enrollment.created_at).order_by(ClassSession.started_at)).all()
    present_ids = set(db.scalars(select(Attendance.session_id).where(Attendance.student_id == enrollment.student_id)).all())
    flags = [int(s.id in present_ids) for s in sessions]
    total, attended = len(flags), sum(flags)
    consecutive = 0
    for value in reversed(flags):
        if value: break
        consecutive += 1
    rate = round(attended / total * 100, 1) if total else None
    level = 'alto' if total >= 3 and (rate < 70 or consecutive >= 3) else 'medio' if total >= 3 and rate < 80 else None
    return {'total': total, 'present': attended, 'absent': total - attended, 'rate': rate, 'consecutive': consecutive, 'level': level, 'recent': flags[-5:]}


def refresh_alerts(db, course_id):
    for e in db.scalars(select(Enrollment).where(Enrollment.course_id == course_id)):
        stats = student_stats(db, e)
        alert = db.scalar(select(Alert).where(Alert.student_id == e.student_id, Alert.course_id == course_id))
        if stats['level']:
            if not alert:
                alert = Alert(student_id=e.student_id, course_id=course_id)
                db.add(alert)
            alert.level = stats['level']
            alert.message = f"Asistencia {stats['rate']}%; {stats['absent']} ausencias de {stats['total']} clases; {stats['consecutive']} ausencias consecutivas."
        elif alert:
            db.delete(alert)


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
