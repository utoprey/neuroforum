'use client'

import { useEffect } from 'react'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import type { UserRead } from '@/lib/types'

/**
 * Mounts at the root. On boot, if we have a persisted accessToken but no
 * cached user, fetch `/users/me` and stash it. If the request 401s the
 * `afterResponse` hook clears the auth state for us.
 */
export function AuthBootstrap() {
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  useEffect(() => {
    if (!hydrated) return
    if (!accessToken) return
    if (user) return
    let cancelled = false
    void (async () => {
      try {
        const me = await api.get('users/me').json<UserRead>()
        if (!cancelled) setUser(me)
      } catch {
        // 401 path is already handled by the api hook (clears tokens).
      }
    })()
    return () => {
      cancelled = true
    }
  }, [hydrated, accessToken, user, setUser])

  return null
}
