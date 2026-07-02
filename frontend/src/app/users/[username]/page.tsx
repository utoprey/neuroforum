'use client'

import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'

import { ProfileView } from '@/components/profile/profile-view'
import { api } from '@/lib/api'
import type { UserRead } from '@/lib/types'

/**
 * Read-only public profile. Backend's ``GET /users/{username}`` returns
 * the same full ``UserRead`` shape as ``/users/me`` (profile + stats),
 * just with the email scrubbed.
 */
export default function PublicProfilePage() {
  const params = useParams<{ username: string }>()
  const username = params.username

  const userQuery = useQuery({
    queryKey: ['users', 'public', username],
    queryFn: () => api.get(`users/${username}`).json<UserRead>(),
    enabled: Boolean(username),
  })

  if (userQuery.isLoading) {
    return <p className="text-muted-foreground">Загружаем профиль…</p>
  }
  if (userQuery.isError || !userQuery.data) {
    return <p className="text-destructive">Пользователь не найден.</p>
  }

  return <ProfileView user={userQuery.data} />
}
