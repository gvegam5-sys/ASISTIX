import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { BiometricAttendance, BiometricTeacher } from './biometric-attendance'

vi.mock('./api', () => ({ api: vi.fn(), ApiError: Error }))
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('releases a late camera permission when the liveness challenge is cancelled', async () => {
  vi.stubGlobal('isSecureContext', true)
  const previousDevices = navigator.mediaDevices
  const actualDescriptor = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')
  let allow!: (stream: MediaStream) => void
  const getUserMedia = vi.fn(() => new Promise<MediaStream>(resolve => { allow=resolve }))
  Object.defineProperty(navigator, 'mediaDevices', { configurable:true, value:{ getUserMedia } })
  try {
    vi.mocked(api).mockImplementation(path => {
      if (path === '/attendance') return Promise.reject(Object.assign(new Error('Requiere verificación'),{code:'BIOMETRIC_REQUIRED'}))
      if (path === '/biometric/challenges') return Promise.resolve({ challenge:'challenge', session_id:1,
        expires_at:new Date(Date.now()+15000).toISOString(), liveness_steps:['center','left','right'] })
      return Promise.resolve({ enrolled:true, physical_capture:true })
    })
    render(<BiometricAttendance Scanner={() => null} refresh={async () => {}}/>)
    await waitFor(() => expect(api).toHaveBeenCalledWith('/biometric/status'))
    fireEvent.change(screen.getByLabelText('Token QR de demostración'), { target:{value:'qr-demo'} })
    fireEvent.click(screen.getByText('Validar QR'))
    await screen.findByText('Mira al centro y mantén el rostro dentro del óvalo.')
    const cameraButton = screen.getByRole<HTMLButtonElement>('button', { name: 'Abrir cámara frontal' })
    await waitFor(() => expect(cameraButton.disabled).toBe(false))
    fireEvent.click(cameraButton)
    expect(getUserMedia).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByText('Cancelar'))
    const stop = vi.fn()
    allow({ getTracks: () => [{ stop }] } as unknown as MediaStream)
    await waitFor(() => expect(stop).toHaveBeenCalledOnce())
    expect(api).toHaveBeenCalledWith('/biometric/challenges/challenge','DELETE')
    expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/confirm'))).toBe(false)
  } finally {
    if (actualDescriptor) Object.defineProperty(navigator,'mediaDevices',actualDescriptor)
    else if (previousDevices) Object.defineProperty(navigator,'mediaDevices',{ value:previousDevices, configurable:true })
    else Reflect.deleteProperty(navigator,'mediaDevices')
  }
})

it('marks facial verification as unnecessary after a conventional QR attendance', async () => {
  vi.mocked(api).mockImplementation(path => path === '/attendance'
    ? Promise.resolve({ message: 'Asistencia registrada' })
    : Promise.resolve({ enrolled: false }))
  render(<BiometricAttendance Scanner={() => null} refresh={async () => {}}/>)
  fireEvent.change(screen.getByLabelText('Token QR de demostración'), { target: { value: 'qr-demo' } })
  fireEvent.click(screen.getByText('Validar QR'))
  const indicator = await screen.findByText('Verificación facial no requerida')
  expect(indicator.getAttribute('data-complete')).toBe('false')
  expect(api).toHaveBeenCalledWith('/attendance', 'POST', { token: 'qr-demo' })
  expect(vi.mocked(api).mock.calls.some(([path]) => path.startsWith('/biometric/challenges'))).toBe(false)
})

it('asks before revocation and reports success only after the server confirms', async () => {
  let complete!: (value: { enrolled: boolean }) => void
  vi.mocked(api).mockImplementation((_, method) => method === 'DELETE'
    ? new Promise(resolve => { complete = resolve })
    : Promise.resolve({ enrolled: true }))
  render(<BiometricAttendance Scanner={() => null} refresh={async () => {}}/>)
  fireEvent.click(screen.getByText('Gestionar derechos biométricos'))
  await screen.findByText('Registro biométrico vigente.')
  fireEvent.click(screen.getByText('Retirar consentimiento y eliminar plantilla'))
  expect(screen.getByRole('group', { name: 'Confirmar retiro' })).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByText('Confirmar eliminación'))
  expect(screen.queryByText(/Consentimiento retirado y plantilla eliminada/)).toBeNull()
  complete({ enrolled: false })
  await screen.findByText(/Consentimiento retirado y plantilla eliminada/)
  expect(screen.getByText('Sin registro biométrico vigente.')).toBeTruthy()
})

it('shows an authorized student name, Spanish reason and approved status', async () => {
  vi.mocked(api).mockImplementation(path => path.endsWith('/reviews')
    ? Promise.resolve([{ id: 'one', student_name: 'Estudiante de ensayo', reason: 'mismatch', approved_at: null }])
    : Promise.resolve({ required: true }))
  render(<BiometricTeacher sessionId={21}/>)
  fireEvent.click(screen.getByText('Laboratorio biométrico de la sesión'))
  await screen.findByText('Verificación biométrica activada')
  fireEvent.click(screen.getByText('Cargar solicitudes'))
  await screen.findByText('Estudiante de ensayo')
  expect(screen.getByText('La muestra facial no coincide')).toBeTruthy()
  fireEvent.click(screen.getByText('Aprobar asistencia'))
  await screen.findByText('Aprobada')
  await waitFor(() => expect(screen.queryByText('Aprobar asistencia')).toBeNull())
  expect(screen.getByText('Asistencia confirmada por revisión docente.')).toBeTruthy()
})
