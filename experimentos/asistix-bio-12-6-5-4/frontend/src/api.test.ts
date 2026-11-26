import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, QR_MESSAGES, setToken } from './api'

const fetchMock = vi.fn<typeof fetch>()
beforeEach(() => { vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); setToken('student-session') })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); setToken('') })
function respond(body: unknown, status = 400) { fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })) }
const register = () => api('/attendance', 'POST', { token: 'scanned-token' })

describe('contrato de errores QR', () => {
  it.each([
    ['ATTENDANCE_DUPLICATE', 409], ['QR_EXPIRED', 401], ['QR_INVALID', 400],
    ['ENROLLMENT_INVALID', 403], ['ROLE_FORBIDDEN', 403], ['AUTH_EXPIRED', 401],
    ['AUTH_REQUIRED', 401], ['AUTH_INVALID', 401], ['CLASS_CLOSED', 409], ['ATTENDANCE_UNAVAILABLE', 503],
  ])('presenta %s sin exponer el detalle técnico', async (code, status) => {
    respond({ code, detail: 'SECRET SQL password_hash scanned-token' }, status as number)
    await expect(register()).rejects.toMatchObject({ code, message: QR_MESSAGES[code], status })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('admite detail estructurado además del formato aditivo actual', async () => {
    respond({ detail: { code: 'QR_EXPIRED', message: 'technical detail' } }, 401)
    await expect(register()).rejects.toMatchObject({ code: 'QR_EXPIRED', message: QR_MESSAGES.QR_EXPIRED })
  })

  it.each([
    ['La sesión está cerrada', 'CLASS_CLOSED'],
    ['No estás matriculado para esta sesión', 'ENROLLMENT_INVALID'],
    ['No tienes permisos para esta acción', 'ROLE_FORBIDDEN'],
    ['Token inválido o vencido', 'QR_INVALID'],
    ['El registro ya existe o tiene relaciones inválidas', 'ATTENDANCE_UNAVAILABLE'],
  ])('admite la respuesta anterior: %s', async (detail, code) => {
    respond({ detail }, 409)
    await expect(register()).rejects.toMatchObject({ code, message: QR_MESSAGES[code] })
  })

  it.each([{ detail: 'UNIQUE constraint failed: SECRET SQL' }, { code: 'UNKNOWN', detail: 'SECRET' }, { detail: [{ input: 'scanned-token' }] }])('oculta errores desconocidos o de validación', async body => {
    respond(body, 503)
    await expect(register()).rejects.toMatchObject({ code: 'ATTENDANCE_UNAVAILABLE', message: QR_MESSAGES.ATTENDANCE_UNAVAILABLE })
  })

  it('mantiene compatibilidad con éxito anterior y autorización Bearer', async () => {
    respond({ message: '¡Asistencia registrada correctamente!', registered_at: '2026-10-22T00:00:00Z' }, 201)
    await expect(register()).resolves.toHaveProperty('message')
    expect(fetchMock).toHaveBeenCalledWith('/api/attendance', expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer student-session' }), body: JSON.stringify({ token: 'scanned-token' }) }))
  })

  it('preserva los mensajes anteriores de otras rutas', async () => {
    respond({ detail: 'Credenciales incorrectas' }, 401)
    await expect(api('/auth/login', 'POST', {})).rejects.toMatchObject({ message: 'Credenciales incorrectas', status: 401 })
  })

  it('no cierra la sesión del usuario cuando el QR vence con HTTP 401', async () => {
    respond({ code: 'QR_EXPIRED', detail: '' }, 401)
    await expect(register()).rejects.toBeInstanceOf(ApiError)
    expect(sessionStorage.getItem('asistix_token')).toBe('student-session')
  })

  it('no reintenta una conexión fallida ni afirma que no se guardó', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Load failed: SECRET'))
    await expect(register()).rejects.toMatchObject({ code: 'CONNECTION_ERROR', message: QR_MESSAGES.CONNECTION_ERROR })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('termina la espera sin reintentar y avisa del resultado incierto', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const assertion = expect(register()).rejects.toMatchObject({ code: 'REQUEST_TIMEOUT', message: QR_MESSAGES.REQUEST_TIMEOUT })
    await vi.advanceTimersByTimeAsync(15000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('no confirma éxito ante una respuesta HTML del proxy', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>SECRET</html>', { status: 200 }))
    await expect(register()).rejects.toMatchObject({ code: 'RESPONSE_INVALID', message: QR_MESSAGES.RESPONSE_INVALID })
  })
})
