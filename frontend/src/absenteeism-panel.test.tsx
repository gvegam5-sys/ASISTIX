import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { AbsenteeismPanel } from './absenteeism-panel'
import type { Absenteeism, RiskRow } from './absenteeism-panel'

afterEach(cleanup)

const period = { start: '2026-11-13', end: '2026-11-19', present: 3, expected: 8, rate: 37.5 }
const analysis: Absenteeism = {
  policy: { min_sessions: 3, high_below: 70, medium_below: 80, high_streak: 3, medium_streak: 2 },
  trend: { previous: period, current: { ...period, present: 0, expected: 0, rate: null }, change: null },
  top_students: [],
  top_courses: [
    { id: 1, name: 'Laboratorio', absent: 1, expected: 1, rate: 100 },
    { id: 2, name: 'Seminario', absent: 3, expected: 8, rate: 37.5 },
  ],
}
const enrollment = (id: number, level: RiskRow['level'], course: string): RiskRow => ({
  id, level, course, student: 'Estudiante', total: 1, absent: 1, rate: 0, consecutive: 1,
  reasons: [], recent: [0],
})

it('shows colors as labeled states and retains grammatical counts', () => {
  const rows = [
    enrollment(1, 'alto', 'Alto'), enrollment(2, 'medio', 'Medio'),
    enrollment(3, 'bajo', 'Bajo'), enrollment(4, 'sin_datos', 'Laboratorio'),
  ]
  const { container } = render(<AbsenteeismPanel analysis={analysis} alerts={rows.slice(0, 2)} rows={rows} role="student"/>)
  for (const [level, label] of [['alto', 'Riesgo alto'], ['medio', 'Riesgo medio'], ['bajo', 'Riesgo bajo'], ['sin_datos', 'Datos insuficientes']]) {
    expect(container.querySelector(`.absence-row .risk-${level}`)?.textContent).toBe(label)
  }
  expect(container.querySelector('.absence-alerts > .risk-alto .risk-badge')).not.toBeNull()
  expect(container.querySelector('.absence-alerts > .risk-medio .risk-badge')).not.toBeNull()
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'sin_datos' } })
  expect(container.querySelectorAll('.absence-row')).toHaveLength(1)
  expect(container.querySelector('.absence-row p')?.textContent).toContain('1 ausencia de 1 clase · Racha activa de 1 ausencia consecutiva')
})

it('keeps ranking order, labels small samples and renders an accessible custom trend bar', () => {
  const { container } = render(<AbsenteeismPanel analysis={analysis} alerts={[]} rows={[]} role="student"/>)
  const rank = screen.getByRole('heading', { name: 'Tus materias con más ausencias' }).parentElement!
  const rows = within(rank).getAllByRole('listitem')
  expect(within(rows[0]).getByText('Laboratorio')).toBeTruthy()
  expect(within(rows[0]).getByText('1 ausencia de 1 asistencia esperada')).toBeTruthy()
  expect(within(rows[0]).getByText('Datos insuficientes')).toBeTruthy()
  expect(within(rows[1]).getByText('3 ausencias de 8 asistencias esperadas')).toBeTruthy()
  expect(within(rows[1]).getByText('de ausencias')).toBeTruthy()
  expect(within(rows[1]).queryByText('Datos insuficientes')).toBeNull()
  const meter = screen.getByRole('meter', { name: 'Periodo anterior' })
  expect(meter.getAttribute('aria-valuenow')).toBe('37.5')
  expect((meter.firstElementChild as HTMLElement).style.width).toBe('37.5%')
  expect(container.querySelector('meter')).toBeNull()
  expect(screen.queryByRole('meter', { name: 'Últimos 7 días' })).toBeNull()
})
