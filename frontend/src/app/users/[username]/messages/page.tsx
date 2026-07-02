'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { api } from '@/lib/api'
import { formatRelative } from '@/lib/notifications'
import type { RecentMessage } from '@/lib/types'

const PAGE_SIZE = 20

function truncate(s: string, max = 200): string {
  if (s.length <= max) return s
  return s.slice(0, max - 1) + '…'
}

export default function UserMessagesPage() {
  const params = useParams<{ username: string }>()
  const username = params.username
  const [pages, setPages] = useState(1)
  const limit = pages * PAGE_SIZE

  const messagesQuery = useQuery({
    queryKey: ['users', username, 'messages', limit],
    queryFn: () =>
      api
        .get(`users/${username}/messages`, {
          searchParams: { limit, offset: 0 },
        })
        .json<RecentMessage[]>(),
    enabled: Boolean(username),
  })

  const items = messagesQuery.data ?? []
  const canLoadMore = items.length === limit

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/users/${username}` as never}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← К профилю @{username}
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight">
          Сообщения @{username}
        </h1>
      </div>

      {messagesQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем…</p>
      )}
      {messagesQuery.isError && (
        <p className="text-destructive">Не удалось загрузить сообщения.</p>
      )}
      {!messagesQuery.isLoading && items.length === 0 && (
        <p className="text-muted-foreground">Сообщений пока нет.</p>
      )}

      {items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.map((m) => (
            <li key={m.id}>
              <Card>
                <CardContent className="flex flex-col gap-2 p-4 text-sm">
                  <p className="whitespace-pre-line">{truncate(m.snippet)}</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>в статье</span>
                    <Link
                      href={
                        `/articles/${m.article_id}#message-${m.id}` as never
                      }
                      className="italic text-primary hover:underline"
                    >
                      «{m.article_title}»
                    </Link>
                    <span>·</span>
                    <span>{formatRelative(m.created_at)}</span>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {canLoadMore && (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            onClick={() => setPages((p) => p + 1)}
            disabled={messagesQuery.isFetching}
          >
            {messagesQuery.isFetching ? 'Загрузка…' : 'Загрузить ещё'}
          </Button>
        </div>
      )}
    </div>
  )
}
