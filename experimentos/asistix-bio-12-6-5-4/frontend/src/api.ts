// Ruta relativa: funciona desde localhost, la IP de la PC y, después, HTTPS.
// Una URL absoluta sigue siendo configurable para despliegues con API separada.
export const API = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '')
export let token = sessionStorage.getItem('asistix_token') || ''
export function setToken(value: string) { token = value; value ? sessionStorage.setItem('asistix_token', value) : sessionStorage.removeItem('asistix_token') }
export const QR_MESSAGES: Record<string, string> = {
  BIOMETRIC_REQUIRED: 'Verifica tu identidad para esta sesión.',
  ATTENDANCE_DUPLICATE: 'Tu asistencia ya está registrada para esta clase. No necesitas registrarla nuevamente.',
  QR_EXPIRED: 'Este QR ya venció. Escanea el código actualizado que muestra tu docente.',
  QR_INVALID: 'No pudimos validar este QR. Escanea el código que muestra tu docente.',
  ENROLLMENT_INVALID: 'No tienes una matrícula válida para esta clase. Consulta con tu docente.',
  ROLE_FORBIDDEN: 'Para registrar asistencia, ingresa con una cuenta de estudiante.',
  AUTH_EXPIRED: 'Tu sesión venció. Inicia sesión nuevamente para registrar tu asistencia.',
  AUTH_REQUIRED: 'Inicia sesión con tu cuenta de estudiante para registrar tu asistencia.',
  AUTH_INVALID: 'No pudimos validar tu acceso. Inicia sesión nuevamente o consulta al administrador.',
  CLASS_CLOSED: 'Esta sesión de clase ya está cerrada. Consulta con tu docente.',
  ATTENDANCE_UNAVAILABLE: 'No pudimos confirmar tu asistencia en este momento. Revisa tu historial y, si el problema continúa, consulta con tu docente.',
  CONNECTION_ERROR: 'No pudimos confirmar tu asistencia. Comprueba tu conexión y revisa tu historial antes de volver a intentarlo.',
  REQUEST_TIMEOUT: 'La respuesta está tardando más de lo esperado. No pudimos confirmar tu asistencia. Revisa tu historial antes de volver a intentarlo.',
  RESPONSE_INVALID: 'No pudimos confirmar tu asistencia. Revisa tu historial antes de volver a intentarlo.',
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) { super(message); this.name = 'ApiError' }
}

const legacyQrCodes: Record<string, string> = {
  'La sesión está cerrada': 'CLASS_CLOSED',
  'No estás matriculado para esta sesión': 'ENROLLMENT_INVALID',
  'No tienes permisos para esta acción': 'ROLE_FORBIDDEN',
  'Cuenta no disponible': 'AUTH_INVALID',
  'Not authenticated': 'AUTH_REQUIRED',
  // Las respuestas antiguas no distinguen entre vencimiento e invalidez.
  'Token inválido o vencido': 'QR_INVALID',
  'Código vencido o desconocido': 'QR_INVALID',
}

function responseError(payload: unknown, status: number, attendance: boolean) {
  const body = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {}
  const detail = body.detail && typeof body.detail === 'object' ? body.detail as Record<string, unknown> : {}
  const code = typeof body.code === 'string' ? body.code : typeof detail.code === 'string' ? detail.code : ''
  const message = typeof body.detail === 'string' ? body.detail : typeof detail.message === 'string' ? detail.message : ''
  if (attendance) {
    const publicCode = Object.hasOwn(QR_MESSAGES, code) ? code : (Object.hasOwn(legacyQrCodes, message) ? legacyQrCodes[message] : '')
      || (status === 422 ? 'QR_INVALID' : status === 401 ? 'AUTH_INVALID' : 'ATTENDANCE_UNAVAILABLE')
    return new ApiError(publicCode, QR_MESSAGES[publicCode], status)
  }
  return new ApiError(code || 'HTTP_ERROR', message || 'No pudimos completar la solicitud. Inténtalo nuevamente.', status)
}

export async function api<T = unknown>(path: string, method = 'GET', body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const attendance = path === '/attendance' && method === 'POST'
  const controller = new AbortController()
  const timer = attendance ? setTimeout(() => controller.abort(), 15000) : undefined
  try {
    // Una sola petición. No se reintenta un POST cuyo resultado podría haberse guardado.
    const binary = body instanceof Blob
    const response = await fetch(API + path, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { 'Content-Type': binary ? body.type : 'application/json' } : {}), ...extraHeaders }, body: binary ? body : body ? JSON.stringify(body) : undefined, ...(attendance ? { signal: controller.signal } : {}) })
    let payload: unknown
    try { payload = await response.json() } catch {
      if (response.ok) throw new ApiError(controller.signal.aborted ? 'REQUEST_TIMEOUT' : 'RESPONSE_INVALID', attendance ? QR_MESSAGES[controller.signal.aborted ? 'REQUEST_TIMEOUT' : 'RESPONSE_INVALID'] : 'No pudimos interpretar la respuesta del servidor.')
    }
    if (!response.ok) throw responseError(payload, response.status, attendance)
    if (attendance && (!payload || typeof payload !== 'object' || typeof (payload as Record<string, unknown>).message !== 'string')) {
      throw new ApiError('RESPONSE_INVALID', QR_MESSAGES.RESPONSE_INVALID, response.status)
    }
    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const code = controller.signal.aborted ? 'REQUEST_TIMEOUT' : 'CONNECTION_ERROR'
    throw new ApiError(code, attendance ? QR_MESSAGES[code] : 'No pudimos conectar con ASISTIX. Comprueba tu conexión e inténtalo de nuevo.')
  } finally { if (timer !== undefined) clearTimeout(timer) }
}
export type AttendanceFilters = { course_id: string; date_from: string; date_to: string }

export function attendanceQuery(filters?: AttendanceFilters) {
  const params = new URLSearchParams()
  if (filters?.course_id) params.set('course_id', filters.course_id)
  if (filters?.date_from) params.set('date_from', filters.date_from)
  if (filters?.date_to) params.set('date_to', filters.date_to)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export async function exportCSV(filters?: AttendanceFilters) {
  const res = await fetch(API + '/reports/attendance.csv' + attendanceQuery(filters), { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('No se pudo descargar el reporte')
  const url = URL.createObjectURL(await res.blob()); const a = document.createElement('a'); a.href = url; a.download = 'asistix-asistencia.csv'; a.click(); URL.revokeObjectURL(url)
}

export async function fetchAttendancePDF(filters: AttendanceFilters) {
  let response: Response
  try {
    response = await fetch(API + '/reports/attendance.pdf' + attendanceQuery(filters), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
  } catch {
    throw new Error('No pudimos conectar con el servidor para generar el PDF.')
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new Error('Inicia sesión de nuevo para exportar el PDF.')
    throw responseError(await response.json().catch(() => null), response.status, false)
  }
  if (response.headers.get('Content-Type')?.split(';', 1)[0].trim() !== 'application/pdf') {
    throw new Error('El servidor no devolvió un documento PDF válido.')
  }
  return response.blob()
}

export async function fetchAttendanceExcel(filters: AttendanceFilters) {
  let response: Response
  try {
    response = await fetch(API + '/reports/attendance.xlsx' + attendanceQuery(filters), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
  } catch {
    throw new Error('No pudimos conectar con el servidor para generar el reporte Excel.')
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new Error('Inicia sesión de nuevo para exportar a Excel.')
    throw responseError(await response.json().catch(() => null), response.status, false)
  }
  if (response.headers.get('Content-Type')?.split(';', 1)[0].trim() !== 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') {
    throw new Error('El servidor no devolvió un archivo Excel válido.')
  }
  return response.blob()
}
