import { describe, expect, it } from 'vitest'
import { formatTime, tickStep, toFrame, toSeconds } from '../format'

describe('format', () => {
  it('formats seconds as clock time', () => {
    expect(formatTime(0)).toBe('0:00')
    expect(formatTime(75.4)).toBe('1:15')
    expect(formatTime(3725)).toBe('1:02:05')
    expect(formatTime(null)).toBe('—')
  })
  it('converts between seconds and frames', () => {
    expect(toFrame(10, 23.976)).toBe(240)
    expect(toSeconds(240, 24)).toBe(10)
  })
  it('picks a readable tick step', () => {
    expect(tickStep(10)).toBe(2)
    expect(tickStep(6646)).toBe(900)
  })
})
