from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = 'sqlite:///./asistix.db'
    jwt_secret: str
    cors_origins: str = 'http://localhost:5173,http://localhost:8080'
    demo_mode: bool = False
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
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
