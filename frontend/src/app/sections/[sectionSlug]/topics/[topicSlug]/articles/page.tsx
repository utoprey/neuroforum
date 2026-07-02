'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import {
  REACTION_GLYPH,
  type ArticlePublic,
  type ReactionKind,
  type TopicRead,
} from '@/lib/types'
import { articleHref } from '@/lib/url-utils'

/**
 * Slug-based mirror of /topics/<topicId>/articles. Uses the new backend
 * routes /sections/{section_slug}/topics/{topic_slug} and
 * /sections/{section_slug}/topics/{topic_slug}/articles so we never
 * leak UUIDs into the URL.
 */
export default function SectionTopicArticlesPage() {
  const params = useParams<{ sectionSlug: string; topicSlug: string }>()
  const sectionSlug = params.sectionSlug
  const topicSlug = params.topicSlug
  const accessToken = useAuthStore((s) => s.accessToken)

  const topicQuery = useQuery({
    queryKey: ['topic-by-slug', sectionSlug, topicSlug],
    queryFn: () =>
      api
        .get(`sections/${sectionSlug}/topics/${topicSlug}`)
        .json<TopicRead>(),
    enabled: Boolean(sectionSlug && topicSlug),
  })

  const articlesQuery = useQuery({
    queryKey: ['topic-by-slug', sectionSlug, topicSlug, 'articles'],
    queryFn: () =>
      api
        .get(`sections/${sectionSlug}/topics/${topicSlug}/articles`, {
          searchParams: { status: 'published', limit: 50 },
        })
        .json<ArticlePublic[]>(),
    enabled: Boolean(sectionSlug && topicSlug),
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {topicQuery.data?.title ?? 'Статьи в теме'}
          </h1>
          {topicQuery.data?.description && (
            <p className="mt-1 text-muted-foreground">
              {topicQuery.data.description}
            </p>
          )}
        </div>
        {accessToken && !topicQuery.data?.is_locked && (
          <Button asChild data-testid="new-article-button">
            <Link
              href={
                `/sections/${sectionSlug}/topics/${topicSlug}/articles/new` as never
              }
            >
              Написать статью
            </Link>
          </Button>
        )}
      </div>

      {articlesQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем статьи…</p>
      )}
      {articlesQuery.isError && (
        <p className="text-destructive">Не удалось загрузить статьи.</p>
      )}
      {articlesQuery.data && articlesQuery.data.length === 0 && (
        <p className="text-muted-foreground">
          В теме пока нет опубликованных статей.
        </p>
      )}
      {articlesQuery.data && articlesQuery.data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {articlesQuery.data.map((a) => (
            <li key={a.id}>
              <Link
                href={articleHref(a) as never}
                className="block"
                data-testid="article-card"
              >
                <Card className="transition-colors hover:bg-accent">
                  <CardHeader>
                    <CardTitle className="text-lg">{a.title}</CardTitle>
                    {a.summary && (
                      <CardDescription>{a.summary}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                    <span>@{a.author.username}</span>
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
