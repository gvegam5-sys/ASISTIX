import { afterEach, expect, it, vi } from 'vitest'
import { captureFrame, FrameCaptureError, waitForVideo } from './liveness-capture'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

function videoFixture() {
  const track = { readyState: 'live', enabled: true, muted: false }
  const state = { readyState: 2, videoWidth: 480, videoHeight: 640, currentTime: 1,
    srcObject: { getVideoTracks: () => [track] }, requestVideoFrameCallback: vi.fn() }
  return { state, track, video: state as unknown as HTMLVideoElement }
}

function canvasFixture() {
  let value = 1
  const context = { drawImage: vi.fn(), getImageData: () => ({ data: Uint8ClampedArray.of(value) }) }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  vi.stubGlobal('crypto', { subtle: { digest: async (_algorithm: string, pixels: Uint8ClampedArray) => Uint8Array.of(pixels[0]).buffer } })
  const encode = vi.spyOn(HTMLCanvasElement.prototype,'toBlob')
    .mockImplementation(done => done(new Blob([new Uint8Array(1000)], { type: 'image/jpeg' })))
  return { context, encode, changePixels: () => { value++ } }
}

it('waits for dimensions and an active video track', async () => {
  vi.useFakeTimers()
  const { state, track, video } = videoFixture()
  state.videoWidth = 0
  track.muted = true
  const ready = vi.fn()
  void waitForVideo(video, () => true).then(ready)
  await vi.advanceTimersByTimeAsync(80)
  expect(ready).not.toHaveBeenCalled()
  state.videoWidth = 480
  track.muted = false
  await vi.advanceTimersByTimeAsync(40)
  expect(ready).toHaveBeenCalledOnce()
})

it('captures with frozen media time and no frame callbacks, while rejecting identical pixels', async () => {
  vi.useFakeTimers()
  const { state, video } = videoFixture()
  const canvas = canvasFixture()
  const first = await captureFrame(video, () => true, [])
  const second = captureFrame(video, () => true, [first])
  await vi.advanceTimersByTimeAsync(300)
  expect(canvas.encode).toHaveBeenCalledOnce()
  canvas.changePixels()
  await vi.advanceTimersByTimeAsync(40)
  const result = await second
  expect(result.capturedAt-first.capturedAt).toBeGreaterThanOrEqual(240)
  expect(result.fingerprint).not.toBe(first.fingerprint)
  expect(state.requestVideoFrameCallback).not.toHaveBeenCalled()
})

it('re-encodes an oversized JPEG and reports encoding failures as technical', async () => {
  const { video } = videoFixture()
  const { encode } = canvasFixture()
  encode.mockImplementationOnce(done => done(new Blob([new Uint8Array(65000)], { type: 'image/jpeg' })))
  expect((await captureFrame(video, () => true, [])).jpeg.size).toBe(1000)
  expect(encode).toHaveBeenNthCalledWith(2, expect.any(Function), 'image/jpeg', 0.64)
  encode.mockImplementation(done => done(null))
  await expect(captureFrame(video, () => true, [])).rejects.toBeInstanceOf(FrameCaptureError)
})
