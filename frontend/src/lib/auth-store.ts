import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import type { UserRead, UserRole } from './types'

/** Lightweight currently-cached user info derived from `/users/me`. */
export interface CachedUser {
  id: string
  username: string
  role: UserRole
  email: string | null
  display_name: string | null
  avatar_url: string | null
}

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: CachedUser | null
  hydrated: boolean
  setTokens: (payload: { accessToken: string; refreshToken?: string | null }) => void
  setUser: (user: UserRead | null) => void
  clearAuth: () => void
  _setHydrated: () => void
}

function pickCachedUser(user: UserRead): CachedUser {
  return {
    id: user.id,
    username: user.username,
    role: user.role,
    email: user.email,
    display_name: user.profile?.display_name ?? null,
    avatar_url: user.profile?.avatar_url ?? null,
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      hydrated: false,
      setTokens: ({ accessToken, refreshToken }) =>
        set((s) => ({
          accessToken,
          refreshToken: refreshToken === undefined ? s.refreshToken : refreshToken,
        })),
      setUser: (user) =>
        set({ user: user ? pickCachedUser(user) : null }),
      clearAuth: () => set({ accessToken: null, refreshToken: null, user: null }),
      _setHydrated: () => set({ hydrated: true }),
    }),
    {
      name: 'neuroforum-auth',
      storage: createJSONStorage(() => localStorage),
      // Persist only tokens. The user object is re-fetched from /users/me
      // on app boot via the AuthBootstrap component.
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
      }),
      onRehydrateStorage: () => (state) => {
        state?._setHydrated()
      },
    },
  ),
)

export type { UserRole }
