"""Initial ASISTIX schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-26 11:37:32.885822
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0001_initial'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the revision."""
    op.create_table(
        'roles',
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['role'], ['roles.name']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'students',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('code'),
    )
    op.create_table(
        'teachers',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('room', sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(['teacher_id'], ['teachers.user_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("level IN ('medio','alto')"),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.user_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'course_id'),
    )
    op.create_table(
        'class_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'enrollments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.user_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'course_id'),
    )
    op.create_table(
        'qr_tokens',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['class_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.String(length=64), nullable=True),
        sa.Column('registered_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['class_sessions.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.user_id']),
        sa.ForeignKeyConstraint(['token_id'], ['qr_tokens.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'session_id'),
        sa.UniqueConstraint('student_id', 'token_id'),
    )


def downgrade() -> None:
    """Reverse the revision."""
    op.drop_table('attendance')
    op.drop_table('qr_tokens')
    op.drop_table('enrollments')
    op.drop_table('class_sessions')
    op.drop_table('alerts')
    op.drop_table('courses')
    op.drop_table('teachers')
    op.drop_table('students')
    op.drop_table('audit_log')
    op.drop_table('users')
    op.drop_table('roles')
