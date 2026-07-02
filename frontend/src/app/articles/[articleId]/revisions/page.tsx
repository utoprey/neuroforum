'use client'

import type { JSONContent } from '@tiptap/react'
import { ArrowLeft, ChevronDown, ChevronRight } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'

import { NotionEditor } from '@/components/editor/notion-editor'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { useArticleRevisions } from '@/lib/hooks/use-revisions'
import { formatRelative } from '@/lib/notifications'
import { parseArticleSlugParam } from '@/lib/url-utils'

export default function ArticleRevisionsPage() {
  const params = useParams<{ articleId: string }>()
  // Accept ``<uuid>`` and ``<uuid>-<slug>``.
  const rawParam = params.articleId ?? ''
  const articleId = parseArticleSlugParam(rawParam).uuid
  const revisionsQuery = useArticleRevisions(articleId, Boolean(articleId))
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  if (revisionsQuery.isLoading) {
    return <p className="text-muted-foreground">Загружаем историю правок…</p>
  }
  if (revisionsQuery.isError) {
    return <p className="text-destructive">Не удалось загрузить историю.</p>
  }

  const revisions = revisionsQuery.data ?? []
  const sorted = [...revisions].sort((a, b) => b.revision - a.revision)

  return (
    <div className="flex flex-col gap-4">
      <Button asChild variant="ghost" size="sm" className="self-start">
        <Link href={`/articles/${articleId}` as never}>
          <ArrowLeft className="h-4 w-4" />К статье
        </Link>
      </Button>

      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">История правок</h1>
        <p className="text-sm text-muted-foreground">
          Снимок контента сохраняется каждый раз, когда статья изменяется после
          публикации.
        </p>
      </header>

      {sorted.length === 0 ? (
        <p className="text-muted-foreground">
          Эта статья ещё не редактировалась после публикации.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {sorted.map((rev) => {
            const isOpen = Boolean(expanded[rev.id])
            const editor = rev.editor
            return (
              <li key={rev.id}>
                <Card data-testid="revision-card" data-revision={rev.revision}>
                  <CardHeader className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">#{rev.revision}</Badge>
                        <Link
                          href={`/users/${editor.username}` as never}
                          className="flex items-center gap-2 text-sm hover:underline"
                        >
                          <Avatar className="h-6 w-6">
                            {editor.avatar_url ? (
                              <AvatarImage
                                src={editor.avatar_url}
                                alt={editor.username}
                              />
                            ) : null}
                            <AvatarFallback>
                              {editor.username[0]?.toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          @{editor.username}
                        </Link>
                        <Badge variant="outline">{rev.editor_role_at_edit}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {formatRelative(rev.created_at)}
                        </span>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setExpanded((prev) => ({
                            ...prev,
                            [rev.id]: !prev[rev.id],
                          }))
                        }
                        data-testid="revision-toggle"
                      >
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                        {isOpen ? 'Свернуть' : 'Просмотреть'}
                      </Button>
                    </div>
                    <p className="text-sm font-medium">{rev.title}</p>
                    {rev.edit_reason && (
                      <p className="text-sm italic text-muted-foreground">
                        Причина: {rev.edit_reason}
                      </p>
                    )}
                  </CardHeader>
                  {isOpen && (
                    <CardContent>
                      <div className="rounded-md border border-border bg-muted/30 p-3">
                        <NotionEditor
                          value={rev.content as unknown as JSONContent}
                          editable={false}
                        />
                      </div>
                    </CardContent>
                  )}
                </Card>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
