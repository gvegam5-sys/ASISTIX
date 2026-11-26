import { expect, it } from 'vitest'
import { formatReportingDate, formatReportingInstant } from './reporting-time'

it('formats UTC instants on the correct Guayaquil day around midnight', () => {
  expect(formatReportingInstant('2026-11-25T04:59:59Z')).toMatch(/^24\/11\/26,/)
  expect(formatReportingInstant('2026-11-25T05:00:00Z')).toMatch(/^25\/11\/26,/)
  expect(formatReportingInstant('2026-11-25T04:59:59Z'))
    .not.toBe(formatReportingInstant('2026-11-25T04:59:59Z', 'UTC'))
})

it('preserves the dashboard calendar date without applying an instant conversion', () => {
  expect(formatReportingDate('2026-11-25')).toBe('25 de noviembre de 2026')
})
