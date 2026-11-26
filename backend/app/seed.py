"""Datos ficticios idempotentes, solo mediante habilitación explícita."""
import argparse
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from .db import Base, engine, SessionLocal, settings
from .models import Role, User, Teacher, Student, Course, Enrollment, ClassSession, Attendance, now
from .security import passwords
from .analytics import refresh_alerts


def seed(*, extended=False, reference=None):
    if not settings.demo_mode:
        raise RuntimeError('Activa DEMO_MODE=true para crear datos ficticios')
    if extended:
        allowed_lab = ('postgresql+psycopg', '127.0.0.1', 5433, 'asistix_lab_pg', 'asistix_lab')
        url = engine.url
        target = (url.drivername, url.host, url.port, url.database, url.username)
        if not os.environ.get('DATABASE_URL') or (engine.dialect.name != 'sqlite' and target != allowed_lab):
            raise RuntimeError('Selecciona una SQLite desechable o el laboratorio PostgreSQL mediante DATABASE_URL')
    current = now()
    reference = current if reference is None else reference
    if reference > current:
        raise ValueError('La referencia UTC no puede estar en el futuro')
    # PostgreSQL schemas are managed by Alembic.
    if engine.dialect.name == 'sqlite' and not extended:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == 'admin@asistix.demo')):
            print('La demostración ya existe; no se modifica.')
            return
        if extended and any(db.execute(select(table).limit(1)).first() is not None
                            for table in Base.metadata.sorted_tables if table.name != 'roles'):
            raise RuntimeError('La semilla ampliada requiere tablas académicas vacías')
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
        courses = [
            ('Ingeniería de Software', teacher, students, 8, 3, False),
            ('Base de Datos', teacher, students, 8, 2, False),
            ('Inteligencia Artificial', teacher, students, 8, 0, False),
        ]
        if extended:
            second_teacher = add('Elena Rivas Demo', 'docente2@asistix.demo', 'teacher')
            db.add(Teacher(user_id=second_teacher.id))
            db.flush()
            courses.extend([
                ('Laboratorio de Proyectos', teacher, students[:1], 1, 1, True),
                ('Redes de Computadoras', second_teacher, students[1:3], 4, 0, False),
            ])
        for n, (name, assigned_teacher, roster, closed_days, missed_recent, include_open) in enumerate(courses):
            c = Course(name=name, code=f'IS-{301+n}', teacher_id=assigned_teacher.id, room=f'Aula {204+n}')
            db.add(c); db.flush()
            for student in roster: db.add(Enrollment(student_id=student.id, course_id=c.id, created_at=reference-timedelta(days=30)))
            db.flush()
            for day in range(closed_days, 0, -1):
                start = reference-timedelta(days=day, hours=n)
                s = ClassSession(course_id=c.id, started_at=start, closed_at=start+timedelta(hours=1))
                db.add(s); db.flush()
                for i, student in enumerate(roster):
                    present = (i + day + n) % (2 if i == 4 else 7) != 0
                    if extended and student is students[0]:
                        present = day > missed_recent
                    if present:
                        db.add(Attendance(student_id=student.id, session_id=s.id, registered_at=start+timedelta(minutes=3)))
            if include_open:
                db.add(ClassSession(course_id=c.id, started_at=reference))
            db.flush()
            refresh_alerts(db, c.id)
        db.commit()
        print('Datos ficticios creados.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extended', action='store_true', help='Incluye cuatro niveles de riesgo y otro docente.')
    parser.add_argument('--reference-utc', help='Fecha ISO 8601 con zona para reproducir las fechas académicas.')
    args = parser.parse_args()
    stamp = None
    if args.reference_utc:
        try:
            stamp = datetime.fromisoformat(args.reference_utc)
            if stamp.utcoffset() is None:
                raise ValueError('Falta la zona horaria')
            stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            parser.error('--reference-utc exige una fecha ISO 8601 con zona horaria')
    seed(extended=args.extended, reference=stamp)
