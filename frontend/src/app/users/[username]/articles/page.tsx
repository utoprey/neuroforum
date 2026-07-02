'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import { articleHref } from '@/lib/url-utils'
import {
  REACTION_GLYPH,
  type ArticlePublic,
  type ReactionKind,
} from '@/lib/types'

const PAGE_SIZE = 20

export default function UserArticlesPage() {
  const params = useParams<{ username: string }>()
  const username = params.username
  const [pages, setPages] = useState(1)
  const limit = pages * PAGE_SIZE

  const articlesQuery = useQuery({
    queryKey: ['users', username, 'articles', limit],
    queryFn: () =>
      api
        .get(`users/${username}/articles`, {
          searchParams: { limit, offset: 0 },
        })
        .json<ArticlePublic[]>(),
    enabled: Boolean(username),
  })

  const items = articlesQuery.data ?? []
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
          Статьи @{username}
        </h1>
      </div>

      {articlesQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем…</p>
      )}
      {articlesQuery.isError && (
        <p className="text-destructive">Не удалось загрузить статьи.</p>
      )}
      {!articlesQuery.isLoading && items.length === 0 && (
        <p className="text-muted-foreground">Статей пока нет.</p>
      )}

      {items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.map((a) => (
            <li key={a.id}>
              <Link href={articleHref(a) as never} className="block">
                <Card className="transition-colors hover:bg-accent">
                  <CardHeader>
                    <CardTitle className="text-lg">{a.title}</CardTitle>
                    {a.summary && (
                      <CardDescription>{a.summary}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                    <span>{a.comment_count} комм.</span>
                    <span>{a.view_count} просм.</span>
                    <ReactionRow counts={a.reaction_counts} />
                  </CardContent>
                </Card>
              </Link>
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
            disabled={articlesQuery.isFetching}
          >
            {articlesQuery.isFetching ? 'Загрузка…' : 'Загрузить ещё'}
          </Button>
        </div>
      )}
    </div>
  )
}

function ReactionRow({
  counts,
}: {
  counts: Partial<Record<ReactionKind, number>>
}) {
  const entries = Object.entries(counts).filter(([, n]) => (n ?? 0) > 0) as [
    ReactionKind,
    number,
  ][]
  if (entries.length === 0) return null
  return (
    <span className="inline-flex gap-1.5">
      {entries.map(([k, n]) => (
        <span key={k}>
          {REACTION_GLYPH[k]} {n}
        </span>
      ))}
    </span>
  )
}
