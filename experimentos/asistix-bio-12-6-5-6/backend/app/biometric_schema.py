"""Explicit migration for the disposable experiment; separate from application metadata."""
from sqlalchemy import Column, DateTime, Integer, LargeBinary, MetaData, String, Table, UniqueConstraint

metadata = MetaData()
policy = Table('biometric_session_policy', metadata, Column('session_id', Integer, primary_key=True))
consent_epoch = Table('biometric_consent_epoch', metadata, Column('student_id', Integer, primary_key=True),
                      Column('revision', Integer, nullable=False))
templates = Table(
    'biometric_templates', metadata, Column('student_id', Integer, primary_key=True),
    Column('version', String(32), nullable=False), Column('notice', String(32), nullable=False),
    Column('consented_at', DateTime, nullable=False), Column('nonce', LargeBinary, nullable=False),
    Column('ciphertext', LargeBinary, nullable=False),
)
challenges = Table(
    'attendance_challenges', metadata, Column('id', String(32), primary_key=True),
    Column('student_id', Integer, nullable=False), Column('session_id', Integer, nullable=False),
    Column('qr_id', String(64), nullable=False), Column('template_version', String(32), nullable=False),
    Column('expires_at', DateTime, nullable=False), Column('closed_at', DateTime),
)
reviews = Table(
    'biometric_reviews', metadata, Column('id', String(32), primary_key=True),
    Column('student_id', Integer, nullable=False), Column('session_id', Integer, nullable=False),
    Column('reason', String(32), nullable=False), Column('created_at', DateTime, nullable=False),
    Column('approved_at', DateTime), Column('approved_by', Integer),
    UniqueConstraint('student_id', 'session_id'),
)
liveness_challenges = Table(
    'attendance_liveness', metadata, Column('challenge_id', String(32), primary_key=True),
    Column('nonce', String(32), nullable=False, unique=True), Column('steps', String(32), nullable=False),
    Column('started_at', DateTime),
)
migrations = Table('biometric_migrations', metadata, Column('version', Integer, primary_key=True))


def migrate():
    from .db import engine

    with engine.begin() as connection:
        metadata.create_all(connection)
        if connection.execute(migrations.select().where(migrations.c.version == 1)).first() is None:
            connection.execute(migrations.insert().values(version=1))


if __name__ == '__main__':
    migrate()
