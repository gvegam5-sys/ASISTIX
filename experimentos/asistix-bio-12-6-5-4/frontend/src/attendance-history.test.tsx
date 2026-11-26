import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api, exportCSV, fetchAttendanceExcel, fetchAttendancePDF } from './api'
import { AttendanceHistory } from './attendance-history'

vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  api: vi.fn(),
  exportCSV: vi.fn(),
  fetchAttendancePDF: vi.fn(),
  fetchAttendanceExcel: vi.fn(),
}))

const courses = [{ id: 2, code: 'IS-302', name: 'Bases de datos' }]
const row = { id: 1, student: 'Estudiante visible', course: courses[0].name, session_id: 8, registered_at: '2026-11-25T05:00:00Z' }
const mockedApi = vi.mocked(api)
const mockedExport = vi.mocked(exportCSV)
const mockedPdf = vi.mocked(fetchAttendancePDF)
const mockedExcel = vi.mocked(fetchAttendanceExcel)

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  mockedApi.mockReset()
  mockedExport.mockReset()
  mockedPdf.mockReset()
  mockedExcel.mockReset()
  vi.unstubAllGlobals()
})

it('exports the applied filters, keeps drafts separate, and clears the query', async () => {
  mockedApi.mockResolvedValue([row])
  mockedExport.mockResolvedValue(undefined)
  render(<AttendanceHistory courses={courses} role="admin"/>)
  await screen.findByText('1 registro encontrado')
  expect(screen.getAllByRole('option').map(option => (option as HTMLOptionElement).value)).toEqual(['', '2'])
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: '2' } })
  fireEvent.change(screen.getByLabelText('Fecha inicial'), { target: { value: '2026-11-25' } })
  fireEvent.change(screen.getByLabelText('Fecha final'), { target: { value: '2026-11-26' } })
  expect(mockedApi).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  await screen.findByText('1 registro encontrado')
  expect(mockedApi).toHaveBeenLastCalledWith('/attendance?course_id=2&date_from=2026-11-25&date_to=2026-11-26')
  fireEvent.change(screen.getByLabelText('Fecha final'), { target: { value: '2026-12-01' } })
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' }))
  await waitFor(() => expect(mockedExport).toHaveBeenCalledWith({
    course_id: '2', date_from: '2026-11-25', date_to: '2026-11-26',
  }))
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }))
  await screen.findByText('1 registro encontrado')
  expect(mockedApi).toHaveBeenLastCalledWith('/attendance')
  expect((screen.getByLabelText('Fecha final') as HTMLInputElement).value).toBe('')
})

it('ignores previous responses and refreshes only with current applied filters', async () => {
  vi.useFakeTimers()
  let resolveOld!: (rows: unknown) => void
  mockedApi.mockImplementation(path => path === '/attendance'
    ? new Promise(resolve => { resolveOld = resolve })
    : Promise.resolve([]) as never)
  render(<AttendanceHistory courses={courses} role="teacher"/>)
  expect(screen.getByText('Cargando registros…')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: '2' } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' })) })
  expect(screen.getByText('No hay registros de tus materias para los filtros aplicados.')).toBeTruthy()
  await act(async () => { resolveOld([row]) })
  expect(screen.queryByText(row.student)).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(mockedApi.mock.calls.map(([path]) => path)).toEqual([
    '/attendance', '/attendance?course_id=2', '/attendance?course_id=2',
  ])
})

it('shows request errors and rejects an inverted range locally', async () => {
  mockedApi.mockRejectedValue(new Error('No pudimos consultar el historial.'))
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('No pudimos consultar el historial.')
  expect((screen.getByRole('button', { name: 'Exportar CSV' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('Fecha inicial'), { target: { value: '2026-11-26' } })
  fireEvent.change(screen.getByLabelText('Fecha final'), { target: { value: '2026-11-25' } })
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  expect(screen.getByText('La fecha inicial debe ser igual o anterior a la fecha final.')).toBeTruthy()
  expect(mockedApi).toHaveBeenCalledTimes(1)
})

it('exposes the same attendance details in the desktop table and mobile cards', async () => {
  mockedApi.mockResolvedValue([row])
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('1 registro encontrado')
  expect(screen.getByRole('region', { name: 'Mis registros de asistencia' })).toBeTruthy()
  expect(screen.getByRole('form', { name: 'Filtros del historial' })).toBeTruthy()
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('columnheader').map(cell => cell.getAttribute('scope'))).toEqual(Array(5).fill('col'))
  const card = within(screen.getByRole('list', { name: 'Registros de asistencia' })).getByRole('listitem')
  expect(Array.from(card.querySelectorAll('dt'), term => term.textContent))
    .toEqual(['Estudiante', 'Materia', 'Sesión', 'Fecha y hora', 'Estado'])
  for (const view of [table, card]) {
    for (const value of [row.student, row.course, '#8', 'Presente']) expect(within(view).getByText(value)).toBeTruthy()
    const timestamp = view.querySelector('time')
    expect(timestamp?.dateTime).toBe(row.registered_at)
    expect(timestamp?.textContent).toMatch(/^25\/11\/26/)
  }
})

it.each([
  ['admin', 'Registros de la institución', 'Todavía no hay asistencias registradas en la institución.'],
  ['teacher', 'Registros de tus materias', 'Todavía no hay asistencias registradas en tus materias asignadas.'],
  ['student', 'Mis registros de asistencia', 'Todavía no tienes asistencias registradas.'],
] as const)('shows the %s history scope when there are no records', async (role, heading, empty) => {
  mockedApi.mockResolvedValue([])
  render(<AttendanceHistory courses={courses} role={role}/>)
  expect(screen.getByRole('heading', { name: heading })).toBeTruthy()
  expect(await screen.findByText(empty)).toBeTruthy()
})

it('generates a PDF from applied filters and releases its download link when they change', async () => {
  const createObjectURL = vi.fn(() => 'blob:attendance-test')
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createObjectURL
    static revokeObjectURL = revokeObjectURL
  })
  mockedApi.mockResolvedValue([row])
  const pdf = new Blob(['%PDF-1.4'], { type: 'application/pdf' })
  let complete!: (blob: Blob) => void
  mockedPdf.mockImplementation(() => new Promise(resolve => { complete = resolve }))
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('1 registro encontrado')
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  await screen.findByText('1 registro encontrado')
  fireEvent.change(screen.getByLabelText('Fecha final'), { target: { value: '2026-11-25' } })
  fireEvent.click(screen.getByRole('button', { name: 'Exportar PDF' }))
  expect(screen.getByText('Preparando el reporte PDF…')).toBeTruthy()
  expect(mockedPdf).toHaveBeenCalledWith({ course_id: '2', date_from: '', date_to: '' })
  await act(async () => { complete(pdf) })
  expect(screen.getByText('¡Reporte PDF generado correctamente!').closest('[role="status"]')).toBeTruthy()
  const download = screen.getByRole('link', { name: 'Abrir o guardar PDF' })
  expect(download.classList.contains('btn')).toBe(true)
  expect(download.getAttribute('href')).toBe('blob:attendance-test')
  expect(download.getAttribute('download')).toBe('asistix-asistencia.pdf')
  expect(download.getAttribute('target')).toBe('_blank')
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }))
  expect(screen.queryByRole('link', { name: 'Abrir o guardar PDF' })).toBeNull()
  expect(screen.queryByText('¡Reporte PDF generado correctamente!')).toBeNull()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:attendance-test')
})

it('shows a PDF error and allows a retry on an empty history', async () => {
  mockedApi.mockResolvedValue([])
  mockedPdf.mockRejectedValue(new Error('No pudimos conectar con el servidor para generar el PDF.'))
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('0 registros encontrados')
  fireEvent.click(screen.getByRole('button', { name: 'Exportar PDF' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Exportar PDF' }) as HTMLButtonElement).disabled).toBe(false)
})

it('confirms the Excel export, uses applied filters and invalidates the old download', async () => {
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:attendance-xlsx')
    static revokeObjectURL = revokeObjectURL
  })
  mockedApi.mockResolvedValue([row])
  mockedExcel.mockResolvedValue(new Blob(['PK']))
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('1 registro encontrado')
  expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Exportar PDF' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
  await screen.findByText('1 registro encontrado')
  fireEvent.change(screen.getByLabelText('Fecha final'), { target: { value: '2026-11-25' } })
  fireEvent.click(screen.getByRole('button', { name: 'Exportar Excel' }))
  expect(mockedExcel).toHaveBeenCalledWith({ course_id: '2', date_from: '', date_to: '' })
  const link = await screen.findByRole('link', { name: 'Guardar Excel' })
  expect(screen.getByText('¡Reporte Excel generado correctamente!').closest('[role="status"]')).toBeTruthy()
  expect(link.getAttribute('href')).toBe('blob:attendance-xlsx')
  expect(link.getAttribute('download')).toBe('asistix-asistencia.xlsx')
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }))
  expect(screen.queryByRole('link', { name: 'Guardar Excel' })).toBeNull()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:attendance-xlsx')
})

it('announces Excel errors and allows retry on empty results', async () => {
  mockedApi.mockResolvedValue([])
  mockedExcel.mockRejectedValue(new Error('No pudimos generar el archivo Excel.'))
  render(<AttendanceHistory courses={courses} role="student"/>)
  await screen.findByText('0 registros encontrados')
  fireEvent.click(screen.getByRole('button', { name: 'Exportar Excel' }))
  expect((await screen.findByRole('alert')).textContent).toBe('No pudimos generar el archivo Excel.')
  expect((screen.getByRole('button', { name: 'Exportar Excel' }) as HTMLButtonElement).disabled).toBe(false)
})
