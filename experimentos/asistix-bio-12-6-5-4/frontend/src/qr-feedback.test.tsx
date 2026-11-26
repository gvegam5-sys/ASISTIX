import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QrFeedback, useQrRegistration } from './qr-feedback'
import { QR_MESSAGES } from './api'

const fetchMock = vi.fn<typeof fetch>()
beforeEach(() => { vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset() })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function Harness({ backgroundError = '', onRecorded = () => {} }: { backgroundError?: string; onRecorded?: () => void | Promise<void> }) {
  const state = useQrRegistration(onRecorded)
  return <><div data-testid="background">{backgroundError}</div><QrFeedback feedback={state.feedback} pending={state.pending}/><button onClick={() => void state.submit('qr-from-camera')} disabled={state.pending}>Registrar</button></>
}

it('conserva el éxito aunque falle la actualización posterior', async () => {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ message: 'ok' }), { status: 201 }))
  const onRecorded = vi.fn().mockRejectedValue(new Error('refresh failed'))
  const view = render(<Harness onRecorded={onRecorded}/>)
  fireEvent.click(screen.getByRole('button'))
  expect((await screen.findByText('¡Listo! Tu asistencia quedó registrada.')).getAttribute('role')).toBe('status')
  await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
  view.rerender(<Harness backgroundError="No pudimos actualizar el panel." onRecorded={onRecorded}/>)
  expect(screen.getByRole('status').textContent).toBe('¡Listo! Tu asistencia quedó registrada.')
  expect(screen.getByTestId('background').textContent).toContain('actualizar')
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it.each(['ATTENDANCE_DUPLICATE', 'QR_EXPIRED', 'QR_INVALID', 'ENROLLMENT_INVALID', 'ROLE_FORBIDDEN', 'AUTH_EXPIRED', 'CLASS_CLOSED'])('presenta %s junto al escáner', async code => {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ code, detail: 'SECRET' }), { status: 409 }))
  render(<Harness/>)
  fireEvent.click(screen.getByRole('button'))
  expect((await screen.findByRole('alert')).textContent).toBe(QR_MESSAGES[code])
  expect(document.body.textContent).not.toContain('SECRET')
})

it('muestra el fallo de red, no reintenta y permite un nuevo intento explícito', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('Load failed'))
  render(<Harness/>)
  fireEvent.click(screen.getByRole('button'))
  expect((await screen.findByRole('alert')).textContent).toBe(QR_MESSAGES.CONNECTION_ERROR)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ message: 'ok' }), { status: 201 }))
  fireEvent.click(screen.getByRole('button'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('quedó registrada'))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('impide envíos simultáneos mientras espera respuesta', async () => {
  let resolve!: (response: Response) => void
  fetchMock.mockImplementation(() => new Promise<Response>(r => { resolve = r }))
  render(<Harness/>)
  const button = screen.getByRole('button')
  fireEvent.click(button); fireEvent.click(button)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toContain('Registrando')
  await act(async () => resolve(new Response(JSON.stringify({ message: 'ok' }), { status: 201 })))
  expect(screen.getByRole('status').textContent).toContain('quedó registrada')
})
