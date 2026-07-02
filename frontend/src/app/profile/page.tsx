'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { ProfileEditModal } from '@/components/profile/profile-edit-modal'
import { ProfileView } from '@/components/profile/profile-view'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import type { UserRead } from '@/lib/types'

/**
 * `/profile` is the *self* view. It mirrors the public profile page but
 * exposes the "Редактировать профиль" CTA and the user's "Сохранённое" list.
 */
export default function ProfilePage() {
  const router = useRouter()
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)
  const setUser = useAuthStore((s) => s.setUser)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const meQuery = useQuery({
    queryKey: ['users', 'me'],
    queryFn: () => api.get('users/me').json<UserRead>(),
    enabled: Boolean(accessToken),
  })

  useEffect(() => {
    if (meQuery.data) setUser(meQuery.data)
  }, [meQuery.data, setUser])

  if (!hydrated || !accessToken) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }
  if (meQuery.isLoading) {
    return <p className="text-muted-foreground">Загрузка профиля…</p>
  }
  if (meQuery.isError || !meQuery.data) {
    return (
      <p className="text-destructive">
        Не удалось загрузить профиль. Попробуйте перезайти.
      </p>
    )
  }

  return (
    <>
      <ProfileView
        user={meQuery.data}
        showSaved
        actions={
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setEditing(true)}
            data-testid="profile-edit-button"
          >
            Редактировать профиль
          </Button>
        }
      />
      <ProfileEditModal
        profile={meQuery.data.profile}
        open={editing}
        onOpenChange={setEditing}
      />
    </>
  )
}
