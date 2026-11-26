import { describe, expect, it, vi } from 'vitest'
import { openFrontCamera, releaseCamera } from './biometric-attendance'

describe('cámara sintética de asistencia', () => {
  function virtualStream() {
    const stopVideo = vi.fn()
    const stopExtra = vi.fn()
    const stream = { getTracks: () => [{ stop: stopVideo }, { stop: stopExtra }] } as unknown as MediaStream
    return { stream, stopVideo, stopExtra }
  }

  it('solicita cámara frontal sin audio y libera todas las pistas', async () => {
    const { stream, stopVideo, stopExtra } = virtualStream()
    const getMedia = vi.fn().mockResolvedValue(stream)
    expect(await openFrontCamera(getMedia, () => false)).toBe(stream)
    expect(getMedia).toHaveBeenCalledWith({ video: { facingMode: { ideal: 'user' } }, audio: false })
    releaseCamera(stream)
    expect(stopVideo).toHaveBeenCalledOnce()
    expect(stopExtra).toHaveBeenCalledOnce()
  })

  it('libera las pistas cuando se cancela mientras el permiso está pendiente', async () => {
    const { stream, stopVideo, stopExtra } = virtualStream()
    let allow!: (stream: MediaStream) => void
    const getMedia = vi.fn(() => new Promise<MediaStream>(resolve => { allow = resolve }))
    let cancelled = false
    const pending = openFrontCamera(getMedia, () => cancelled)
    cancelled = true
    allow(stream)
    await expect(pending).resolves.toBeNull()
    expect(stopVideo).toHaveBeenCalledOnce()
    expect(stopExtra).toHaveBeenCalledOnce()
  })

  it('propaga el permiso denegado sin crear pistas', async () => {
    const denied = new DOMException('Denegado', 'NotAllowedError')
    await expect(openFrontCamera(vi.fn().mockRejectedValue(denied), () => false)).rejects.toBe(denied)
  })
})
