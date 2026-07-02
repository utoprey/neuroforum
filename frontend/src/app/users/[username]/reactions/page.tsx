'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { api } from '@/lib/api'
import { formatRelative } from '@/lib/notifications'
import { REACTION_GLYPH, type UserReactionItem } from '@/lib/types'

const PAGE_SIZE = 20

export default function UserReactionsPage() {
  const params = useParams<{ username: string }>()
  const username = params.username
  const [pages, setPages] = useState(1)
  const limit = pages * PAGE_SIZE

  const reactionsQuery = useQuery({
    queryKey: ['users', username, 'reactions', limit],
    queryFn: () =>
      api
        .get(`users/${username}/reactions`, {
          searchParams: { limit, offset: 0 },
        })
        .json<UserReactionItem[]>(),
    enabled: Boolean(username),
  })

  const items = reactionsQuery.data ?? []
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
          Реакции @{username}
        </h1>
      </div>

      {reactionsQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем…</p>
      )}
      {reactionsQuery.isError && (
        <p className="text-destructive">Не удалось загрузить реакции.</p>
      )}
      {!reactionsQuery.isLoading && items.length === 0 && (
        <p className="text-muted-foreground">
          @{username} ещё ничего не лайкнул(а).
        </p>
      )}

      {items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.map((r) => {
            const href =
              r.target_type === 'message'
                ? `/articles/${r.article_id}#message-${r.target_id}`
                : `/articles/${r.article_id}`
            const targetWord =
              r.target_type === 'article' ? 'статью' : 'сообщение в'
            return (
              <li
                key={`${r.target_type}-${r.target_id}-${r.reacted_at}`}
              >
                <Card>
                  <CardContent className="flex flex-col gap-2 p-4 text-sm">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-lg leading-none">
                        {REACTION_GLYPH[r.kind]}
                      </span>
                      <span>{targetWord}</span>
                      <Link
                        href={href as never}
                        className="italic text-primary hover:underline"
                      >
                        «{r.article_title}»
                      </Link>
                    </div>
                    {r.snippet && (
                      <p className="line-clamp-3 italic text-muted-foreground">
                        {r.snippet}
                      </p>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {formatRelative(r.reacted_at)}
                    </span>
                  </CardContent>
                </Card>
              </li>
            )
          })}
        </ul>
      )}

      {canLoadMore && (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            onClick={() => setPages((p) => p + 1)}
            disabled={reactionsQuery.isFetching}
          >
            {reactionsQuery.isFetching ? 'Загрузка…' : 'Загрузить ещё'}
          </Button>
        </div>
      )}
    </div>
  )
}
