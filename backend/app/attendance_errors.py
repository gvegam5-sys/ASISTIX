"""Contrato público de errores QR; nunca contiene detalles de persistencia."""
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

MESSAGES = {
    'ATTENDANCE_DUPLICATE': 'Tu asistencia ya está registrada para esta clase. No necesitas registrarla nuevamente.',
    'QR_EXPIRED': 'Este QR ya venció. Escanea el código actualizado que muestra tu docente.',
    'QR_INVALID': 'No pudimos validar este QR. Escanea el código que muestra tu docente.',
    'ENROLLMENT_INVALID': 'No tienes una matrícula válida para esta clase. Consulta con tu docente.',
    'ROLE_FORBIDDEN': 'Para registrar asistencia, ingresa con una cuenta de estudiante.',
    'AUTH_EXPIRED': 'Tu sesión venció. Inicia sesión nuevamente para registrar tu asistencia.',
    'AUTH_REQUIRED': 'Inicia sesión con tu cuenta de estudiante para registrar tu asistencia.',
    'AUTH_INVALID': 'No pudimos validar tu acceso. Inicia sesión nuevamente o consulta al administrador.',
    'CLASS_CLOSED': 'Esta sesión de clase ya está cerrada. Consulta con tu docente.',
    'ATTENDANCE_UNAVAILABLE': 'No pudimos confirmar tu asistencia en este momento. Revisa tu historial y, si el problema continúa, consulta con tu docente.',
}


class AttendanceError(HTTPException):
    def __init__(self, code, status_code):
        super().__init__(status_code, MESSAGES[code])
        self.code = code


def error_response(code, status):
    # detail sigue siendo texto para clientes anteriores; code es aditivo.
    return JSONResponse(status_code=status, content={'detail': MESSAGES[code], 'code': code})


class AttendanceRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except AttendanceError as error:
                return error_response(error.code, error.status_code)
            except RequestValidationError:
                return error_response('QR_INVALID', 422)
            except SQLAlchemyError:
                return error_response('ATTENDANCE_UNAVAILABLE', 503)
            except Exception:
                # No devolvemos excepciones, SQL, credenciales ni el token recibido.
                return error_response('ATTENDANCE_UNAVAILABLE', 500)

        return handler
