from datetime import timedelta
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .db import settings, get_db
from .models import User, now
from .attendance_errors import AttendanceError

passwords = PasswordHash.recommended()
bearer = HTTPBearer()


def sign(payload, seconds=3600):
    return jwt.encode({**payload, 'exp': now() + timedelta(seconds=seconds), 'iss': 'asistix'}, settings.jwt_secret, algorithm='HS256')


def decode(token, kind, *, attendance=False):
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'], issuer='asistix', options={'require': ['exp', 'iss', 'kind']})
        if payload['kind'] != kind:
            raise ValueError()
        return payload
    except jwt.ExpiredSignatureError:
        if attendance:
            raise AttendanceError('QR_EXPIRED' if kind == 'qr' else 'AUTH_EXPIRED', 401)
        raise HTTPException(401, 'Token inválido o vencido')
    except (jwt.PyJWTError, ValueError):
        if attendance:
            raise AttendanceError('QR_INVALID' if kind == 'qr' else 'AUTH_INVALID', 401)
        raise HTTPException(401, 'Token inválido o vencido')


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    payload = decode(credentials.credentials, 'access')
    user = db.get(User, int(payload['sub']))
    if not user or not user.active:
        raise HTTPException(401, 'Cuenta no disponible')
    return user


def roles(*allowed):
    def check(user: User = Depends(current_user)):
        if user.role not in allowed:
            raise HTTPException(403, 'No tienes permisos para esta acción')
        return user
    return check


attendance_bearer = HTTPBearer(auto_error=False)


def attendance_student(credentials: HTTPAuthorizationCredentials | None = Depends(attendance_bearer), db: Session = Depends(get_db)):
    if not credentials:
        raise AttendanceError('AUTH_REQUIRED', 401)
    payload = decode(credentials.credentials, 'access', attendance=True)
    try:
        user_id = int(payload['sub'])
    except (KeyError, TypeError, ValueError):
        raise AttendanceError('AUTH_INVALID', 401)
    user = db.get(User, user_id)
    if not user or not user.active:
        raise AttendanceError('AUTH_INVALID', 401)
    if user.role != 'student':
        raise AttendanceError('ROLE_FORBIDDEN', 403)
    return user
