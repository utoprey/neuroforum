'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import { articleHref } from '@/lib/url-utils'
import { useAuthStore } from '@/lib/auth-store'
import { REACTION_GLYPH, type ReactionKind, type SavedArticleRead } from '@/lib/types'

export default function MySavedPage() {
  const router = useRouter()
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const savedQuery = useQuery({
    queryKey: ['me', 'saved'],
    queryFn: () =>
      api.get('me/saved', { searchParams: { limit: 100 } }).json<SavedArticleRead[]>(),
    enabled: Boolean(accessToken),
  })

  if (!hydrated || !accessToken) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-3xl font-semibold tracking-tight">Сохранённое</h1>

      {savedQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем…</p>
      )}
      {savedQuery.isError && (
        <p className="text-destructive">Не удалось загрузить сохранённое.</p>
      )}
      {savedQuery.data && savedQuery.data.length === 0 && (
        <p className="text-muted-foreground">У вас пока нет сохранённых статей.</p>
      )}
      {savedQuery.data && savedQuery.data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {savedQuery.data.map((s) => (
            <li key={s.article_id}>
              <Link href={articleHref(s.article) as never} className="block">
                <Card className="transition-colors hover:bg-accent">
                  <CardHeader>
                    <CardTitle className="text-lg">{s.article.title}</CardTitle>
                    {s.article.summary && (
                      <CardDescription>{s.article.summary}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                    <span>@{s.article.author.username}</span>
                    <span>
                      сохранено {new Date(s.saved_at).toLocaleDateString('ru')}
                    </span>
                    <ReactionRow counts={s.article.reaction_counts} />
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
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
