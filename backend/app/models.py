from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .schema import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(Base):
    __tablename__ = 'roles'
    name: Mapped[str] = mapped_column(String(20), primary_key=True)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(ForeignKey('roles.name'))
    active: Mapped[bool] = mapped_column(default=True)


class Student(Base):
    __tablename__ = 'students'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)


class Teacher(Base):
    __tablename__ = 'teachers'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)


class Course(Base):
    __tablename__ = 'courses'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(30), unique=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.user_id'))
    room: Mapped[str] = mapped_column(String(60), default='Aula 204')


class Enrollment(Base):
    __tablename__ = 'enrollments'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.user_id'))
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint('student_id', 'course_id'),)


class ClassSession(Base):
    __tablename__ = 'class_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    started_at: Mapped[datetime] = mapped_column(default=now)
    closed_at: Mapped[datetime | None]


class QRToken(Base):
    __tablename__ = 'qr_tokens'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('class_sessions.id'))
    issued_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime]


class Attendance(Base):
    __tablename__ = 'attendance'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.user_id'))
    session_id: Mapped[int] = mapped_column(ForeignKey('class_sessions.id'))
    token_id: Mapped[str | None] = mapped_column(ForeignKey('qr_tokens.id'))
    registered_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint('student_id', 'session_id'), UniqueConstraint('student_id', 'token_id'))


class Alert(Base):
    __tablename__ = 'alerts'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.user_id'))
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint('student_id', 'course_id'), CheckConstraint("level IN ('medio','alto')"))


class Audit(Base):
    __tablename__ = 'audit_log'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)
