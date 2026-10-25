import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, ME, mockApi, renderAt, VIDEO } from './helpers'

const signedOut = () => json({ detail: 'sign in required' }, 401)

describe('sign-in', () => {
  it('shows the sign-in form without a session', async () => {
    mockApi({ 'GET /api/auth/me': signedOut })
    renderAt('/videos/7')
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows a generic error for bad credentials', async () => {
    mockApi({ 'GET /api/auth/me': signedOut,
      'POST /api/auth/login': () => json({ detail: 'invalid username or password' }, 401) })
    renderAt('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'alex')
    await userEvent.type(screen.getByLabelText('Password'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid username or password')
  })

  it('signs in to the dashboard and signs out again', async () => {
    const calls = mockApi({ 'GET /api/auth/me': signedOut, 'POST /api/auth/login': ME,
      'GET /api/videos': [VIDEO], 'GET /api/participants': [], 'POST /api/auth/logout': () => new Response(null, { status: 204 }) })
    renderAt('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'alex')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/login')?.body).toEqual({ username: 'alex', password: 'correct horse' })
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('returns to sign-in when the session expires mid-work', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': signedOut, 'GET /api/participants': signedOut })
    renderAt('/')
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})
