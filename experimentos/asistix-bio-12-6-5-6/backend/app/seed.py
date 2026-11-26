"""Datos ficticios idempotentes, solo mediante habilitación explícita."""
from datetime import timedelta
from sqlalchemy import select
from .db import Base, engine, SessionLocal, settings
from .models import Role, User, Teacher, Student, Course, Enrollment, ClassSession, Attendance, now
from .security import passwords
from .analytics import refresh_alerts


def seed():
    if not settings.demo_mode: raise RuntimeError('Activa DEMO_MODE=true para crear datos ficticios')
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == 'admin@asistix.demo')):
            print('La demostración ya existe; no se modifica.')
            return
        for role in ['admin', 'teacher', 'student']:
            if not db.get(Role, role): db.add(Role(name=role))
        db.flush()
        def add(name, email, role):
            u = User(name=name, email=email, role=role, password_hash=passwords.hash('Asistix2026!'))
            db.add(u); db.flush()
            return u
        add('Administrador Demo', 'admin@asistix.demo', 'admin')
        teacher = add('Valentina Torres', 'docente@asistix.demo', 'teacher')
        db.add(Teacher(user_id=teacher.id)); db.flush()
        students = []
        for i, name in enumerate(['Isaac Mendoza', 'Camila Ortiz', 'Mateo Rivera', 'Sofía Vera', 'Daniel López', 'Lucía Castro', 'Andrés Ríos', 'Emma Santos']):
            student = add(name, 'estudiante@asistix.demo' if i == 0 else f'estudiante{i+1}@asistix.demo', 'student')
            db.add(Student(user_id=student.id, code=f'DEMO-{i+1:03}')); students.append(student)
        db.flush()
        for n, name in enumerate(['Ingeniería de Software', 'Base de Datos', 'Inteligencia Artificial']):
            c = Course(name=name, code=f'IS-{301+n}', teacher_id=teacher.id, room=f'Aula {204+n}')
            db.add(c); db.flush()
            for student in students: db.add(Enrollment(student_id=student.id, course_id=c.id, created_at=now()-timedelta(days=30)))
            db.flush()
            for day in range(8, 0, -1):
                start = now()-timedelta(days=day, hours=n)
                s = ClassSession(course_id=c.id, started_at=start, closed_at=start+timedelta(hours=1))
                db.add(s); db.flush()
                for i, student in enumerate(students):
                    if (i+day+n) % (2 if i == 4 else 7) != 0:
                        db.add(Attendance(student_id=student.id, session_id=s.id, registered_at=start+timedelta(minutes=3)))
            db.flush(); refresh_alerts(db, c.id)
        db.commit()
        print('Datos ficticios creados. Clave demo: Asistix2026!')


if __name__ == '__main__': seed()
