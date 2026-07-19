import ky, { HTTPError } from 'ky'

import { useAuthStore } from './auth-store'

const PREFIX_URL =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

/**
 * Shared `ky` instance for talking to the FastAPI backend.
 *
 * Auth: reads `accessToken` from the Zustand store on every request.
 * 401 handling (MVP): clear auth + redirect to /login from the client.
 * A proper refresh-flow via POST /auth/refresh is left as a TODO — for now
 * users re-login when their access token expires.
 */
export const api = ky.create({
  prefixUrl: PREFIX_URL,
  timeout: 15_000,
  retry: {
    limit: 1,
    methods: ['get'],
    statusCodes: [408, 502, 503, 504],
  },
  hooks: {
    beforeRequest: [
      (request) => {
        const token = useAuthStore.getState().accessToken
        if (token) {
          request.headers.set('Authorization', `Bearer ${token}`)
        }
      },
    ],
    afterResponse: [
      async (request, _options, response) => {
        if (response.status === 401) {
          // TODO: implement real refresh flow:
          //   1. call POST /auth/refresh with the refreshToken from store
          //   2. on success — update accessToken and retry original request
          //   3. on failure — clear auth and redirect
          // For MVP we just clear and let the UI redirect.
          const url = new URL(request.url)
          const isAuthCheck = url.pathname.endsWith('/users/me')
          useAuthStore.getState().clearAuth()
          if (
            typeof window !== 'undefined' &&
            !isAuthCheck &&
            !window.location.pathname.startsWith('/login') &&
            !window.location.pathname.startsWith('/register')
          ) {
            window.location.assign('/login')
          }
        }
        return response
      },
    ],
  },
})

/**
 * Extract a human-readable error message from an unknown thrown value.
 * Handles `ky` HTTPError JSON `{detail: "..."}` responses from FastAPI.
 */
export async function extractErrorMessage(
  err: unknown,
  fallback = 'Что-то пошло не так',
): Promise<string> {
  if (err instanceof HTTPError) {
    try {
      const body = (await err.response.clone().json()) as
        | { detail?: string | { msg?: string }[] }
        | undefined
      if (typeof body?.detail === 'string') return body.detail
      if (Array.isArray(body?.detail)) {
        return body.detail
          .map((d) => (typeof d === 'string' ? d : (d?.msg ?? '')))
          .filter(Boolean)
          .join('; ')
      }
    } catch {
      // fall through
    }
    return `${fallback} (HTTP ${err.response.status})`
  }
  if (err instanceof Error) return err.message
  return fallback
}

export { HTTPError }
