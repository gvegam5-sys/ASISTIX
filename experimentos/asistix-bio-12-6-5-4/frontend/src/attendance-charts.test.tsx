import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AttendanceByCourse, AttendanceCharts, WeeklyAttendanceTooltip, formatAttendancePercent } from './attendance-charts'

vi.mock('recharts', async importOriginal => ({
  ...await importOriginal<typeof import('recharts')>(),
  ResponsiveContainer: () => null,
}))

afterEach(cleanup)

it('shows one Ecuadorian decimal for all rates and keeps null distinct from zero', () => {
  expect(formatAttendancePercent(81.2)).toBe('81,2\u00a0%')
  const { container } = render(<AttendanceByCourse courses={[
    { name: 'Completa', present: 8, expected: 8, rate: 100 },
    { name: 'Cero', present: 0, expected: 8, rate: 0 },
    { name: 'Sin sesiones', present: 0, expected: 0, rate: null },
  ]}/>)
  expect(screen.getByText(/^100,0\s%$/)).toBeTruthy()
  expect(screen.getByText(/^0,0\s%$/)).toBeTruthy()
  expect(screen.getByText('Sin datos')).toBeTruthy()
  const bars = [...container.querySelectorAll<HTMLElement>('.attendance-course-fill')]
  expect(bars.map(bar => bar.style.width)).toEqual(['100%', '0%'])
  expect(container.querySelectorAll('.attendance-course-track-empty')).toHaveLength(1)
  const first = screen.getByText('Completa').closest('details')!
  expect(within(first).getByText('Asistencias registradas').nextElementSibling?.textContent).toBe('8')
})

it('identifies both weekly series in the visible legend', () => {
  render(<AttendanceCharts courses={[]} week={[]}/>)
  const legend = screen.getByRole('list', { name: 'Leyenda de asistencia semanal' })
  expect(within(legend).getByText('Asistencias registradas').firstElementChild?.classList.contains('attendance-chart-line-expected')).toBe(false)
  expect(within(legend).getByText('Asistencias esperadas').firstElementChild?.classList.contains('attendance-chart-line-expected')).toBe(true)
})

it('preserves the institutional calendar date, quantities and rate in the weekly tooltip', () => {
  const { rerender } = render(<WeeklyAttendanceTooltip point={{ date: '2026-11-25', present: 0, expected: 16 }}/>)
  expect(screen.getByText('25 de noviembre de 2026')).toBeTruthy()
  expect(screen.getByText('16')).toBeTruthy()
  expect(screen.getByText(/^0,0\s%$/)).toBeTruthy()
  rerender(<WeeklyAttendanceTooltip point={{ date: '2026-11-25', present: 0, expected: 0 }}/>)
  expect(screen.getByText('Sin datos')).toBeTruthy()
})
