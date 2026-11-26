from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta, datetime
from collections import defaultdict, deque
import csv
import io
import secrets
import threading
import time
from typing import Annotated
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .db import Base, engine, get_db, settings
from .models import User, Role, Student, Teacher, Course, Enrollment, ClassSession, QRToken, Attendance, Audit, now
from .security import passwords, sign, decode, current_user, roles, attendance_student
from .attendance_errors import AttendanceError, AttendanceRoute
from .analytics import attendance_overview, attendance_timelines, percentage, trailing_absences, refresh_alerts, experimental_model
from .reporting_time import REPORTING_ZONE, reporting_date, reporting_day_bounds


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    from .db import SessionLocal
    with SessionLocal() as db:
        for name in ['admin', 'teacher', 'student']:
            if not db.get(Role, name): db.add(Role(name=name))
        db.commit()
    yield


app = FastAPI(title='ASISTIX API', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(','), allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Authorization', 'Content-Type'])


def audit(db, user, action):
    db.add(Audit(actor_id=user.id, action=action))


def commit(db):
    try: db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'El registro ya existe o tiene relaciones inválidas')


def user_view(u):
    return {'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role, 'active': u.active}


def visible_courses(db, u):
    query = select(Course)
    if u.role == 'teacher': query = query.where(Course.teacher_id == u.id)
    if u.role == 'student': query = query.join(Enrollment).where(Enrollment.student_id == u.id)
    return db.scalars(query.order_by(Course.id)).all()


def course_access(db, u, course_id):
    course = next((c for c in visible_courses(db, u) if c.id == course_id), None)
    if not course: raise HTTPException(404, 'Materia no disponible')
    return course


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


attempts = defaultdict(deque)
attempt_lock = threading.Lock()
dummy_hash = passwords.hash(secrets.token_urlsafe(24))


@app.get('/health')
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {'status': 'ok', 'demo': settings.demo_mode}


@app.post('/auth/login')
def login(data: Login, request: Request, db: Session = Depends(get_db)):
    key = request.client.host if request.client else 'unknown'
    with attempt_lock:
        q = attempts[key]
        while q and q[0] < time.monotonic() - 60: q.popleft()
        if len(q) >= 20: raise HTTPException(429, 'Demasiados intentos. Espera un minuto.')
        q.append(time.monotonic())
    u = db.scalar(select(User).where(User.email == data.email.lower()))
    valid = passwords.verify(data.password, u.password_hash if u else dummy_hash)
    if not u or not valid or not u.active: raise HTTPException(401, 'Credenciales incorrectas')
    audit(db, u, 'login')
    db.commit()
    return {'access_token': sign({'sub': str(u.id), 'kind': 'access'}), 'token_type': 'bearer', 'user': user_view(u)}


@app.get('/auth/me')
def me(u: User = Depends(current_user)):
    return user_view(u)


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(pattern='^(admin|teacher|student)$')


@app.get('/users')
def users(u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    return [user_view(x) for x in db.scalars(select(User).order_by(User.id))]


@app.post('/users', status_code=201)
def create_user(data: UserCreate, u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    obj = User(name=data.name, email=data.email.lower(), password_hash=passwords.hash(data.password), role=data.role)
    db.add(obj)
    try: db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'El correo ya está registrado')
    if obj.role == 'student': db.add(Student(user_id=obj.id, code=f'EST-{obj.id:05}'))
    if obj.role == 'teacher': db.add(Teacher(user_id=obj.id))
    audit(db, u, f'create_user:{obj.id}')
    commit(db)
    return user_view(obj)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    active: bool | None = None


@app.patch('/users/{user_id}')
def update_user(user_id: int, data: UserUpdate, u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    obj = db.get(User, user_id)
    if not obj: raise HTTPException(404, 'Usuario no encontrado')
    if obj.id == u.id and data.active is False: raise HTTPException(400, 'No puedes desactivar tu propia cuenta')
    for key, value in data.model_dump(exclude_none=True).items(): setattr(obj, key, value)
    audit(db, u, f'update_user:{obj.id}')
    commit(db)
    return user_view(obj)


class CourseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=30)
    teacher_id: int
    room: str = Field(default='Aula 204', max_length=60)


@app.get('/courses')
def courses(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{'id': c.id, 'name': c.name, 'code': c.code, 'room': c.room, 'teacher_id': c.teacher_id, 'teacher': db.get(User, c.teacher_id).name, 'students': db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == c.id))} for c in visible_courses(db, u)]


@app.post('/courses', status_code=201)
def create_course(data: CourseCreate, u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    if not db.get(Teacher, data.teacher_id): raise HTTPException(400, 'Selecciona un docente válido')
    c = Course(**data.model_dump())
    db.add(c)
    audit(db, u, f'create_course:{data.code}')
    commit(db)
    return {'id': c.id}


@app.patch('/courses/{course_id}')
def edit_course(course_id: int, data: CourseCreate, u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    c = course_access(db, u, course_id)
    if not db.get(Teacher, data.teacher_id): raise HTTPException(400, 'Docente inválido')
    for k, v in data.model_dump().items(): setattr(c, k, v)
    audit(db, u, f'update_course:{c.id}')
    commit(db)
    return {'id': c.id}


class EnrollCreate(BaseModel):
    student_id: int
    course_id: int


@app.post('/enrollments', status_code=201)
def enroll(data: EnrollCreate, u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    if not db.get(Student, data.student_id) or not db.get(Course, data.course_id): raise HTTPException(400, 'Estudiante o materia inválidos')
    db.add(Enrollment(**data.model_dump()))
    audit(db, u, f'enroll:{data.student_id}:{data.course_id}')
    commit(db)
    return {'message': 'Matrícula registrada'}


@app.get('/sessions')
def sessions(u: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = [c.id for c in visible_courses(db, u)]
    return [{'id': s.id, 'course_id': s.course_id, 'started_at': s.started_at.isoformat()+'Z', 'closed_at': s.closed_at.isoformat()+'Z' if s.closed_at else None} for s in db.scalars(select(ClassSession).where(ClassSession.course_id.in_(ids)).order_by(ClassSession.started_at.desc()).limit(100))]


@app.post('/courses/{course_id}/sessions', status_code=201)
def start_session(course_id: int, u: User = Depends(roles('teacher', 'admin')), db: Session = Depends(get_db)):
    course_access(db, u, course_id)
    # Serializa aperturas de una misma materia en PostgreSQL.
    db.scalar(select(Course).where(Course.id == course_id).with_for_update())
    if db.scalar(select(ClassSession).where(ClassSession.course_id == course_id, ClassSession.closed_at.is_(None))): raise HTTPException(409, 'Esta materia ya tiene una sesión abierta')
    s = ClassSession(course_id=course_id)
    db.add(s)
    audit(db, u, f'start_session:{course_id}')
    commit(db)
    return {'id': s.id}


@app.post('/sessions/{session_id}/close')
def close_session(session_id: int, u: User = Depends(roles('teacher', 'admin')), db: Session = Depends(get_db)):
    s = db.scalar(select(ClassSession).where(ClassSession.id == session_id).with_for_update())
    if not s: raise HTTPException(404, 'Sesión no encontrada')
    course_access(db, u, s.course_id)
    if s.closed_at: raise HTTPException(409, 'La sesión ya está cerrada')
    s.closed_at = now()
    db.flush()
    refresh_alerts(db, s.course_id)
    audit(db, u, f'close_session:{s.id}')
    commit(db)
    return {'message': 'Sesión cerrada; alertas actualizadas'}


@app.get('/sessions/{session_id}/qr')
def qr(session_id: int, u: User = Depends(roles('teacher', 'admin')), db: Session = Depends(get_db)):
    s = db.scalar(select(ClassSession).where(ClassSession.id == session_id).with_for_update())
    if not s: raise HTTPException(404, 'Sesión no encontrada')
    course_access(db, u, s.course_id)
    if s.closed_at: raise HTTPException(409, 'Sesión cerrada')
    t = db.scalar(select(QRToken).where(QRToken.session_id == s.id, QRToken.expires_at > now()).order_by(QRToken.issued_at.desc()))
    if not t:
        t = QRToken(id=secrets.token_urlsafe(24), session_id=s.id, expires_at=now()+timedelta(seconds=30))
        db.add(t)
        commit(db)
    expiration = int(t.expires_at.replace(tzinfo=__import__('datetime').timezone.utc).timestamp())
    token = sign({'kind': 'qr', 'jti': t.id, 'sid': s.id}, max(1, expiration-int(time.time())))
    return {'token': token, 'expires_at': t.expires_at.isoformat()+'Z', 'server_time': now().isoformat()+'Z'}


class Scan(BaseModel):
    token: str = Field(min_length=20, max_length=2048)


attendance_router = APIRouter(route_class=AttendanceRoute)


@attendance_router.post('/attendance', status_code=201)
def scan(data: Scan, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
    p = decode(data.token, 'qr', attendance=True)
    if not isinstance(p.get('jti'), str) or type(p.get('sid')) is not int:
        raise AttendanceError('QR_INVALID', 400)
    t = db.get(QRToken, p['jti'])
    if not t or t.session_id != p['sid']:
        raise AttendanceError('QR_INVALID', 400)
    if t.expires_at <= now():
        raise AttendanceError('QR_EXPIRED', 400)
    s = db.scalar(select(ClassSession).where(ClassSession.id == t.session_id).with_for_update())
    if not s:
        raise AttendanceError('QR_INVALID', 400)
    # También comprueba vigencia después de esperar el bloqueo de la sesión.
    if t.expires_at <= now():
        raise AttendanceError('QR_EXPIRED', 400)
    if s.closed_at:
        raise AttendanceError('CLASS_CLOSED', 409)
    e = db.scalar(select(Enrollment).where(Enrollment.student_id == u.id, Enrollment.course_id == s.course_id))
    if not e or e.created_at > s.started_at:
        raise AttendanceError('ENROLLMENT_INVALID', 403)
    duplicate = select(Attendance.id).where(Attendance.student_id == u.id, Attendance.session_id == s.id)
    if db.scalar(duplicate) is not None:
        raise AttendanceError('ATTENDANCE_DUPLICATE', 409)
    db.add(Attendance(student_id=u.id, session_id=s.id, token_id=t.id))
    audit(db, u, f'attendance:{s.id}')
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Conserva la restricción de unicidad, incluso con peticiones concurrentes.
        # Otros errores de integridad no se presentan como una asistencia existente.
        if db.scalar(duplicate) is not None:
            raise AttendanceError('ATTENDANCE_DUPLICATE', 409)
        raise AttendanceError('ATTENDANCE_UNAVAILABLE', 503)
    return {'code': 'ATTENDANCE_RECORDED', 'message': '¡Listo! Tu asistencia quedó registrada.', 'registered_at': now().isoformat()+'Z'}


app.include_router(attendance_router)


@dataclass(frozen=True)
class AttendanceFilters:
    course_id: int | None
    start_utc: datetime | None
    end_utc: datetime | None
    date_from: date | None
    date_to: date | None


def attendance_filters(
    course_id: Annotated[int | None, Query(gt=0)] = None,
    date_from: Annotated[str | None, Query(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')] = None,
    date_to: Annotated[str | None, Query(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')] = None,
) -> AttendanceFilters:
    try:
        first = date.fromisoformat(date_from) if date_from else None
        last = date.fromisoformat(date_to) if date_to else None
        start_utc = reporting_day_bounds(first)[0] if first else None
        end_utc = reporting_day_bounds(last)[1] if last else None
    except (ValueError, OverflowError):
        raise HTTPException(422, 'Selecciona fechas válidas.') from None
    if first and last and first > last:
        raise HTTPException(422, 'La fecha inicial debe ser igual o anterior a la fecha final.')
    return AttendanceFilters(course_id, start_utc, end_utc, first, last)


def records(db, u, session_id=None, *, filters: AttendanceFilters | None = None, max_rows: int | None = None):
    ids = [c.id for c in visible_courses(db, u)]
    query = select(Attendance, ClassSession, User, Course).join(ClassSession, Attendance.session_id == ClassSession.id).join(User, Attendance.student_id == User.id).join(Course, ClassSession.course_id == Course.id).where(Course.id.in_(ids))
    if u.role == 'student': query = query.where(Attendance.student_id == u.id)
    if session_id: query = query.where(ClassSession.id == session_id)
    if filters:
        if filters.course_id is not None:
            if filters.course_id not in ids:
                raise HTTPException(404, 'Materia no disponible')
            query = query.where(Course.id == filters.course_id)
        if filters.start_utc is not None:
            query = query.where(Attendance.registered_at >= filters.start_utc)
        if filters.end_utc is not None:
            query = query.where(Attendance.registered_at < filters.end_utc)
    query = query.order_by(Attendance.registered_at.desc(), Attendance.id.desc())
    if max_rows is not None:
        query = query.limit(max_rows)
    return [{'id': a.id, 'student': student.name, 'student_id': student.id, 'course': c.name, 'session_id': s.id, 'registered_at': a.registered_at.isoformat()+'Z'} for a, s, student, c in db.execute(query)]


@app.get('/attendance')
def attendance(filters: Annotated[AttendanceFilters, Depends(attendance_filters)], session_id: int | None = None, u: User = Depends(current_user), db: Session = Depends(get_db)):
    return records(db, u, session_id, filters=filters)


@app.get('/sessions/{session_id}/roster')
def roster(session_id: int, u: User = Depends(roles('teacher', 'admin')), db: Session = Depends(get_db)):
    s = db.get(ClassSession, session_id)
    if not s: raise HTTPException(404, 'Sesión no encontrada')
    course_access(db, u, s.course_id)
    present = {a['student_id'] for a in records(db, u, session_id)}
    return [{'id': student.id, 'name': student.name, 'status': 'Presente' if student.id in present else 'Ausente' if s.closed_at else 'Pendiente'} for student in db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(Enrollment.course_id == s.course_id, Enrollment.created_at <= s.started_at))]


@app.get('/dashboard')
def dashboard(u: User = Depends(current_user), db: Session = Depends(get_db)):
    cs = visible_courses(db, u)
    as_of = now()
    today = reporting_date(as_of)
    overview = attendance_overview(db, cs, u.id if u.role == 'student' else None, as_of)
    total = sum(c['expected'] for c in overview['courses'])
    present = sum(c['present'] for c in overview['courses'])
    start_utc, end_utc = reporting_day_bounds(today)
    today_query = select(func.count()).select_from(Attendance).join(ClassSession).where(
        ClassSession.course_id.in_([c.id for c in cs]),
        Attendance.registered_at >= start_utc,
        Attendance.registered_at < end_utc,
    )
    if u.role == 'student':
        today_query = today_query.where(Attendance.student_id == u.id)
    return {**overview, 'demo': settings.demo_mode, 'today': db.scalar(today_query),
            'rate': percentage(present, total), 'absent_rate': percentage(total - present, total),
            'analysis': experimental_model([]), 'timezone': REPORTING_ZONE.key, 'local_date': today.isoformat()}


@app.get('/reports/attendance.csv')
def report(filters: Annotated[AttendanceFilters, Depends(attendance_filters)], u: User = Depends(current_user), db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Estudiante', 'Materia', 'Sesión', 'Fecha UTC'])
    for r in records(db, u, filters=filters):
        # Impide fórmulas al abrir el CSV en una hoja de cálculo.
        clean = lambda v: "'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v
        writer.writerow([clean(r['student']), clean(r['course']), r['session_id'], r['registered_at']])
    audit(db, u, 'export_attendance')
    db.commit()
    return Response('\ufeff'+output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="asistix-asistencia.csv"'})


@app.get('/reports/attendance.pdf', responses={200: {'content': {'application/pdf': {}}}}, response_class=Response)
def attendance_pdf(filters: Annotated[AttendanceFilters, Depends(attendance_filters)], u: User = Depends(current_user), db: Session = Depends(get_db)):
    from .attendance_pdf import MAX_PDF_RECORDS, PDF_SLOT, render_attendance_pdf
    if not PDF_SLOT.acquire(blocking=False):
        raise HTTPException(503, 'Hay otro PDF en preparación. Inténtalo nuevamente en unos segundos.',
                            headers={'Retry-After': '3'})
    try:
        rows = records(db, u, filters=filters, max_rows=MAX_PDF_RECORDS + 1)
        if len(rows) > MAX_PDF_RECORDS:
            limit = f'{MAX_PDF_RECORDS:,}'.replace(',', ' ')
            raise HTTPException(422, f'El PDF supera {limit} registros. Selecciona una materia o un periodo más corto.')
        course = course_access(db, u, filters.course_id) if filters.course_id is not None else None
        document = render_attendance_pdf(
            rows, role=u.role, generated_by=u.name, generated_at=now(), demo=settings.demo_mode,
            course=f'{course.code} · {course.name}' if course else None,
            date_from=filters.date_from, date_to=filters.date_to,
        )
    finally:
        PDF_SLOT.release()
    return Response(
        document,
        media_type='application/pdf',
        headers={
            'Content-Disposition': 'attachment; filename="asistix-asistencia.pdf"',
            'Cache-Control': 'private, no-store',
        },
    )


@app.get('/reports/attendance.xlsx', responses={200: {'content': {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {},
}}}, response_class=Response)
def attendance_xlsx(filters: Annotated[AttendanceFilters, Depends(attendance_filters)], u: User = Depends(current_user), db: Session = Depends(get_db)):
    from .attendance_xlsx import MAX_XLSX_RECORDS, XLSX_MIME, XLSX_SLOT, render_attendance_xlsx

    if not XLSX_SLOT.acquire(blocking=False):
        raise HTTPException(503, 'Hay otro reporte Excel en preparación. Inténtalo nuevamente en unos segundos.',
                            headers={'Retry-After': '3'})
    try:
        rows = records(db, u, filters=filters, max_rows=MAX_XLSX_RECORDS + 1)
        if len(rows) > MAX_XLSX_RECORDS:
            limit = f'{MAX_XLSX_RECORDS:,}'.replace(',', ' ')
            raise HTTPException(422, f'El reporte Excel supera {limit} registros. Selecciona una materia o un periodo más corto.')
        course = course_access(db, u, filters.course_id) if filters.course_id is not None else None
        document = render_attendance_xlsx(
            rows, role=u.role, generated_by=u.name, generated_at=now(), demo=settings.demo_mode,
            course=f'{course.code} · {course.name}' if course else None,
            date_from=filters.date_from, date_to=filters.date_to,
        )
    finally:
        XLSX_SLOT.release()
    return Response(
        document, media_type=XLSX_MIME, headers={
            'Content-Disposition': 'attachment; filename="asistix-asistencia.xlsx"',
            'Cache-Control': 'private, no-store',
        },
    )


@app.get('/audit')
def audit_log(u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    return [{'actor_id': a.actor_id, 'action': a.action, 'date': a.created_at.isoformat()+'Z'} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]


@app.post('/analytics/model')
def evaluate_model(u: User = Depends(roles('admin')), db: Session = Depends(get_db)):
    if settings.demo_mode:
        return {'status': 'insufficient_data', 'message': 'Evaluación deshabilitada con datos ficticios. Se mantienen las reglas estadísticas.'}
    rows = []
    for _, _, history in attendance_timelines(db):
        flags = [present for _, present in history]
        for i in range(5, len(flags)):
            recent = flags[i-5:i]
            rows.append({'date': history[i][0], 'features': [sum(recent) / 5, trailing_absences(recent)],
                         'next_absent': 1 - flags[i]})
    rows.sort(key=lambda r: r['date'])
    result = experimental_model(rows)
    audit(db, u, 'evaluate_attendance_model')
    db.commit()
    return result
