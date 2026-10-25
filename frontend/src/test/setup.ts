import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom does not implement media seeking; a plain property lets tests observe seeks.
Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
  configurable: true,
  get() { return (this as { _t?: number })._t ?? 0 },
  set(value: number) { (this as { _t?: number })._t = value },
})

// jsdom has no native modal-dialog behavior.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
