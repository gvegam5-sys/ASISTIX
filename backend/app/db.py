from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = 'sqlite:///./asistix.db'
    jwt_secret: str
    cors_origins: str = 'http://localhost:5173,http://localhost:8080'
    demo_mode: bool = False
    absenteeism_min_sessions: int = Field(default=3, ge=1)
    absenteeism_high_below: float = Field(default=70, ge=0, le=100)
    absenteeism_medium_below: float = Field(default=80, ge=0, le=100)
    absenteeism_high_streak: int = Field(default=3, ge=1)
    absenteeism_medium_streak: int = Field(default=2, ge=1)

    @model_validator(mode='after')
    def validate_absenteeism(self):
        if (self.absenteeism_high_below >= self.absenteeism_medium_below
                or self.absenteeism_medium_streak >= self.absenteeism_high_streak):
            raise ValueError('Los umbrales de riesgo deben estar ordenados')
        return self

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
