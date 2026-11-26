from pathlib import Path

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = 'sqlite:///./asistix.db'
    jwt_secret: str
    cors_origins: str = 'http://localhost:5173,http://localhost:8080'
    demo_mode: bool = False
    biometric_lab: bool = False
    biometric_key_file: str = ''
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
backend_dir = Path(__file__).resolve().parents[1]
expected_database = backend_dir / 'asistix-biometria.db'
primary_database = backend_dir.parents[2] / 'backend' / 'asistix.db'
demo_database = backend_dir.parents[2] / 'tools/asistix-pruebas/backend/asistix-pruebas.db'
synthetic_database = backend_dir.parents[2] / 'tools/asistix-bio-12-6-4/backend/asistix-biometria.db'
database_url = make_url(settings.database_url)
private_pilot = os.environ.get('ASISTIX_PHYSICAL_GATEWAY') == '12654'
if private_pilot:
    from comprobar_aislamiento import is_appcontainer

    if not is_appcontainer():
        raise RuntimeError('Physical database requires the restricted gateway')
    private_directory = Path(os.environ['ASISTIX_PRIVATE_PILOT_ROOT'])
    expected_database = private_directory / 'state/asistix-biometria.db'
    biometric_key = private_directory / 'keys/biometric.key'
else:
    biometric_key = backend_dir.parent / 'tools/instance/biometric.key'

if (
    database_url.drivername != 'sqlite'
    or database_url.database != expected_database.as_posix()
    or database_url.query
    or not expected_database.is_file()
    or expected_database.resolve() != expected_database
    or expected_database.stat().st_nlink != 1
    or (not private_pilot and any(expected_database.samefile(protected) for protected in
                                  (primary_database, demo_database, synthetic_database)))
    or not settings.demo_mode
):
    raise RuntimeError('La instancia de pruebas requiere su propia base SQLite y DEMO_MODE=true')
if len(settings.jwt_secret) < 32:
    raise RuntimeError('JWT_SECRET debe contener al menos 32 caracteres')
engine = create_engine(settings.database_url, connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {})
if settings.database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db
