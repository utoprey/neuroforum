'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import type {
  ConversationRead,
  UserPublic,
} from '@/lib/types'

export default function DirectMessagesIndexPage() {
  const router = useRouter()
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)
  const me = useAuthStore((s) => s.user)
  const [newOpen, setNewOpen] = useState(false)

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const listQuery = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api.get('conversations').json<ConversationRead[]>(),
    enabled: Boolean(accessToken),
    refetchInterval: 30_000,
  })

  if (!hydrated || !accessToken) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Личные сообщения</h1>
        <Button onClick={() => setNewOpen(true)} data-testid="dm-new-button">
          Новый чат
        </Button>
      </div>

      {listQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем диалоги…</p>
      )}
      {listQuery.isError && (
        <p className="text-destructive">Не удалось загрузить диалоги.</p>
      )}
      {listQuery.data && listQuery.data.length === 0 && (
        <p className="text-muted-foreground">
          У вас пока нет диалогов. Начните первый!
        </p>
      )}

      <ul className="flex flex-col gap-3">
        {listQuery.data?.map((conv) => {
          const other =
            conv.participants.find((p) => p.id !== me?.id) ?? conv.participants[0]
          return (
            <li key={conv.id}>
              <Link href={`/dm/${conv.id}` as never} className="block">
                <Card className="transition-colors hover:bg-accent">
                  <CardHeader className="flex flex-row items-center gap-3 space-y-0">
                    <Avatar className="h-10 w-10">
                      {other?.avatar_url ? (
                        <AvatarImage
                          src={other.avatar_url}
                          alt={other.username}
                        />
                      ) : null}
                      <AvatarFallback>
                        {(other?.username ?? '?')[0].toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div className="flex flex-1 flex-col gap-0.5">
                      <CardTitle className="text-base">
                        {other?.display_name || `@${other?.username ?? '???'}`}
                      </CardTitle>
                      <span className="text-xs text-muted-foreground">
                        {conv.last_message_at
                          ? new Date(conv.last_message_at).toLocaleString('ru')
                          : 'Нет сообщений'}
                      </span>
                    </div>
                    {conv.unread_count > 0 && (
                      <span
                        className="inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-full bg-destructive px-2 text-xs font-semibold text-destructive-foreground"
                        data-testid="dm-unread-badge"
                      >
                        {conv.unread_count}
                      </span>
                    )}
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground">
                    @{other?.username ?? '???'}
                  </CardContent>
                </Card>
              </Link>
            </li>
          )
        })}
      </ul>

      <NewDmDialog open={newOpen} onOpenChange={setNewOpen} />
    </div>
  )
}

function NewDmDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const router = useRouter()
  const me = useAuthStore((s) => s.user)
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(q.trim()), 200)
    return () => window.clearTimeout(handle)
  }, [q])

  const searchQuery = useQuery({
    queryKey: ['users', 'search', debounced],
    queryFn: () =>
      api
        .get('users/search', { searchParams: { q: debounced, limit: 10 } })
        .json<UserPublic[]>(),
    enabled: open && debounced.length >= 2,
  })

  const startMutation = useMutation({
    mutationFn: (target_user_id: string) =>
      api
        .post('conversations/dm', { json: { target_user_id } })
        .json<{ id: string }>(),
    onSuccess: (conv) => {
      onOpenChange(false)
      setQ('')
      router.push(`/dm/${conv.id}` as never)
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось открыть чат'))
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новый чат</DialogTitle>
          <DialogDescription>
            Найдите пользователя по имени или @username
          </DialogDescription>
        </DialogHeader>
        <Input
          placeholder="@user или имя…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
        <div className="max-h-72 overflow-auto">
          {debounced.length < 2 && (
            <p className="px-2 py-2 text-sm text-muted-foreground">
              Введите минимум 2 символа.
            </p>
          )}
          {searchQuery.isLoading && (
            <p className="px-2 py-2 text-sm text-muted-foreground">Ищем…</p>
          )}
          {searchQuery.data && searchQuery.data.length === 0 && (
            <p className="px-2 py-2 text-sm text-muted-foreground">
              Никого не найдено.
            </p>
          )}
          <ul>
            {searchQuery.data
              ?.filter((u) => u.id !== me?.id)
              .map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-accent disabled:opacity-50"
                    disabled={startMutation.isPending}
                    onClick={() => startMutation.mutate(u.id)}
                  >
                    <Avatar className="h-8 w-8">
                      {u.avatar_url ? (
                        <AvatarImage src={u.avatar_url} alt={u.username} />
                      ) : null}
                      <AvatarFallback>{u.username[0].toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <span className="flex flex-col">
                      <span className="text-sm font-medium">
                        {u.display_name || `@${u.username}`}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        @{u.username}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        </div>
      </DialogContent>
    </Dialog>
  )
}
