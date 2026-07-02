'use client'

import { useQuery } from '@tanstack/react-query'
import { Pencil, Plus } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useState } from 'react'

import { CreateTopicModal } from '@/components/forum/create-topic-modal'
import { EditSectionModal } from '@/components/forum/edit-section-modal'
import { TopicCategoryTabs } from '@/components/forum/topic-category-tabs'
import { Badge } from '@/components/ui/badge'
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
  TOPIC_KIND_LABEL,
  type SectionRead,
  type TopicKind,
  type TopicRead,
} from '@/lib/types'

const DEFAULT_KIND: TopicKind = 'news'

export default function SectionTopicsPage() {
  const params = useParams<{ sectionSlug: string }>()
  const sectionSlug = params.sectionSlug
  const search = useSearchParams()
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)

  const kindParam = (search.get('kind') as TopicKind | null) ?? DEFAULT_KIND
  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)

  const sectionQuery = useQuery({
    queryKey: ['section', sectionSlug],
    queryFn: () => api.get(`sections/${sectionSlug}`).json<SectionRead>(),
    enabled: Boolean(sectionSlug),
  })

  const topicsQuery = useQuery({
    queryKey: ['section', sectionSlug, 'topics', kindParam],
    queryFn: () =>
      api
        .get(`sections/${sectionSlug}/topics`, {
          searchParams: { kind: kindParam, limit: 50 },
        })
        .json<TopicRead[]>(),
    enabled: Boolean(sectionSlug),
  })

  const section = sectionQuery.data
  const isAdmin = user?.role === 'admin'
  const isModOrAdmin = user?.role === 'moderator' || user?.role === 'admin'
  const canCreateNews = isModOrAdmin
  const canCreateNonNews = Boolean(accessToken)
  const canCreate = kindParam === 'news' ? canCreateNews : canCreateNonNews

  function setKind(k: TopicKind) {
    const next = new URLSearchParams(search.toString())
    next.set('kind', k)
    router.replace(`/sections/${sectionSlug}/topics?${next.toString()}` as never)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {section?.title ?? 'Раздел'}
          </h1>
          {section?.description && (
            <p className="mt-1 text-muted-foreground">{section.description}</p>
          )}
        </div>
        {isAdmin && section && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditOpen(true)}
          >
            <Pencil className="mr-1 h-4 w-4" />
            Редактировать раздел
          </Button>
        )}
      </div>

      <TopicCategoryTabs value={kindParam} onChange={setKind} />

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">{TOPIC_KIND_LABEL[kindParam]}</h2>
        {canCreate && (
          <Button onClick={() => setCreateOpen(true)} size="sm">
            <Plus className="mr-1 h-4 w-4" />
            Создать тему
          </Button>
        )}
      </div>

      {topicsQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем темы…</p>
      )}
      {topicsQuery.isError && (
        <p className="text-destructive">Не удалось загрузить темы.</p>
      )}
      {topicsQuery.data && topicsQuery.data.length === 0 && (
        <p className="text-muted-foreground">В этой категории пока пусто.</p>
      )}
      {topicsQuery.data && topicsQuery.data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {topicsQuery.data.map((t) => (
            <li key={t.id}>
              <Link
                href={
                  `/sections/${sectionSlug}/topics/${t.slug}/articles` as never
                }
                className="block"
              >
                <Card className="transition-colors hover:bg-accent">
                  <CardHeader>
                    <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
                      {t.title}
                      {t.is_pinned && (
                        <Badge variant="secondary">закреплено</Badge>
                      )}
                      {t.is_locked && (
                        <Badge variant="outline">закрыто</Badge>
                      )}
                    </CardTitle>
                    {t.description && (
                      <CardDescription>{t.description}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-3 text-sm text-muted-foreground">
                    <span>@{t.created_by.username}</span>
                    <span>{new Date(t.created_at).toLocaleDateString('ru')}</span>
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {section && (
        <CreateTopicModal
          open={createOpen}
          onOpenChange={setCreateOpen}
          sectionSlug={sectionSlug}
          kind={kindParam}
        />
      )}
      {section && isAdmin && (
        <EditSectionModal
          open={editOpen}
          onOpenChange={setEditOpen}
          section={section}
        />
      )}
    </div>
  )
}
