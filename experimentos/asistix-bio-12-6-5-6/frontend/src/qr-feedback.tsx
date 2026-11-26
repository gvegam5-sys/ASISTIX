import { useRef, useState } from 'react'
import { api, ApiError, QR_MESSAGES } from './api'

type Feedback = { type: 'success' | 'error'; code: string; message: string } | null

export function useQrRegistration(onRecorded: () => void | Promise<void>) {
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [pending, setPending] = useState(false)
  const submitting = useRef(false)

  async function submit(value: string) {
    if (submitting.current) return
    submitting.current = true
    setPending(true)
    setFeedback(null)
    let recorded = false
    try {
      await api('/attendance', 'POST', { token: value })
      setFeedback({ type: 'success', code: 'ATTENDANCE_RECORDED', message: '¡Listo! Tu asistencia quedó registrada.' })
      recorded = true
    } catch (error) {
      const safe = error instanceof ApiError ? error : new ApiError('ATTENDANCE_UNAVAILABLE', QR_MESSAGES.ATTENDANCE_UNAVAILABLE)
      setFeedback({ type: 'error', code: safe.code, message: safe.message })
    } finally {
      submitting.current = false
      setPending(false)
    }
    // Actualizar el panel nunca cambia el resultado confirmado del registro.
    if (recorded) void Promise.resolve().then(onRecorded).catch(() => {})
  }

  return { feedback, pending, submit }
}

export function QrFeedback({ feedback, pending }: { feedback: Feedback; pending: boolean }) {
  if (pending) return <p role="status" aria-live="polite">Registrando tu asistencia…</p>
  if (!feedback) return null
  return <div className={feedback.type === 'success' ? 'success' : 'error'} role={feedback.type === 'success' ? 'status' : 'alert'} aria-live={feedback.type === 'success' ? 'polite' : 'assertive'} data-code={feedback.code}>{feedback.message}</div>
}
