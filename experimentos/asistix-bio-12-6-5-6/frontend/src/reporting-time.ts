export const REPORTING_TIME_ZONE = 'America/Guayaquil'

export function formatReportingInstant(value: string, timeZone = REPORTING_TIME_ZONE) {
  return new Intl.DateTimeFormat('es-EC', {
    dateStyle: 'short', timeStyle: 'short', timeZone,
  }).format(new Date(value))
}

export function formatReportingDate(value: string) {
  // A date from the dashboard already belongs to the institutional calendar.
  return new Intl.DateTimeFormat('es-EC', { dateStyle: 'long', timeZone: 'UTC' })
    .format(new Date(`${value}T00:00:00Z`))
}
