import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { BiometricAttendance, BiometricTeacher } from './biometric-attendance'

vi.mock('./api', () => ({ api: vi.fn(), ApiError: Error }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

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
