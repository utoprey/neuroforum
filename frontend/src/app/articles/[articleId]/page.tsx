'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { AIProposalsPanel } from '@/components/articles/ai-proposals-panel'
import { AIReviewButton } from '@/components/articles/ai-review-button'
import { AIReviewsSection } from '@/components/articles/ai-reviews-section'
import { DeleteArticleDialog } from '@/components/articles/delete-article-dialog'
import { CommentThread } from '@/components/comments/comment-thread'
import { NotionEditor } from '@/components/editor/notion-editor'
import { ReactionBar } from '@/components/reactions/reaction-bar'
import { ShareDropdown } from '@/components/share/share-dropdown'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { useArticleRevisions } from '@/lib/hooks/use-revisions'
import type { ArticleRead } from '@/lib/types'
import { parseArticleSlugParam } from '@/lib/url-utils'

export default function ArticlePage() {
  const params = useParams<{ articleId: string }>()
  // The route segment may be either ``<uuid>`` (legacy) or
  // ``<uuid>-<slug>`` (new canonical). The slug is purely cosmetic — we
  // always hit the API with the bare UUID so a renamed slug still resolves.
  const articleId = parseArticleSlugParam(params.articleId ?? '').uuid
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const qc = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const articleKey = ['article', articleId] as const
  const articleQuery = useQuery({
    queryKey: articleKey,
    queryFn: () => api.get(`articles/${articleId}`).json<ArticleRead>(),
    enabled: Boolean(articleId),
  })

  const saveMutation = useMutation({
    mutationFn: async (action: 'save' | 'unsave') => {
      if (action === 'save') {
        await api.post(`me/saved/${articleId}`)
      } else {
        await api.delete(`me/saved/${articleId}`)
      }
    },
    onSuccess: (_data, action) => {
      setSaved(action === 'save')
    },
    onError: async (err) => {
      setActionError(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  const restoreMutation = useMutation({
    mutationFn: () => api.post(`articles/${articleId}/publish`).json<ArticleRead>(),
    onSuccess: async () => {
      toast.success('Статья восстановлена')
      await qc.invalidateQueries({ queryKey: articleKey })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось восстановить'))
    },
  })

  // Revisions counter for the link near the comment thread. Only authenticated
  // users can call the endpoint; for guests we just hide the counter.
  const revisionsQuery = useArticleRevisions(
    articleId,
    Boolean(articleId && accessToken),
  )

  if (articleQuery.isLoading) {
    return <p className="text-muted-foreground">Загружаем статью…</p>
  }
  if (articleQuery.isError || !articleQuery.data) {
    return <p className="text-destructive">Статья не найдена или недоступна.</p>
  }

  const article = articleQuery.data
  const isAuthor = user?.id === article.author.id
  const isAdmin = user?.role === 'admin'
  const isModOrAdmin = user?.role === 'moderator' || isAdmin
  const canEdit = isAuthor || isModOrAdmin
  const isDraft = article.status === 'draft'
  const isArchived = article.status === 'archived'
  const revisionsCount = revisionsQuery.data?.length ?? 0

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {isDraft && <Badge variant="secondary">Черновик</Badge>}
          {article.status === 'hidden' && (
            <Badge variant="destructive">Скрыто модератором</Badge>
          )}
          {article.status === 'archived' && (
            <Badge variant="outline">В архиве</Badge>
          )}
        </div>
        <h1 className="text-4xl font-bold tracking-tight">{article.title}</h1>
        {article.summary && (
          <p className="text-lg text-muted-foreground">{article.summary}</p>
        )}
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <Link
            href={`/users/${article.author.username}` as never}
            className="flex items-center gap-2 hover:text-foreground"
          >
            <Avatar className="h-7 w-7">
              {article.author.avatar_url ? (
                <AvatarImage
                  src={article.author.avatar_url}
                  alt={article.author.username}
                />
              ) : null}
              <AvatarFallback>{article.author.username[0]}</AvatarFallback>
            </Avatar>
            @{article.author.username}
          </Link>
          {article.published_at && (
            <span>{new Date(article.published_at).toLocaleString('ru')}</span>
          )}
          <span>{article.view_count} просмотров</span>
          <span>{article.comment_count} комментариев</span>
        </div>
      </header>

      <NotionEditor value={article.content} editable={false} />

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <ReactionBar
          scope="articles"
          parentId={article.id}
          counts={article.reaction_counts}
          invalidateKey={articleKey}
        />
        {accessToken && (
          <Button
            type="button"
            variant={saved ? 'secondary' : 'outline'}
            size="sm"
            onClick={() => {
              setActionError(null)
              saveMutation.mutate(saved ? 'unsave' : 'save')
            }}
            disabled={saveMutation.isPending}
            data-testid="save-article-button"
          >
            {saved ? 'Сохранено' : 'Сохранить'}
          </Button>
        )}
        {canEdit && (
          <>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/articles/${article.id}/edit` as never}>
                Редактировать
              </Link>
            </Button>
            <AIReviewButton articleId={article.id} />
            {isDraft && (
              <Button
                type="button"
                size="sm"
                onClick={async () => {
                  setActionError(null)
                  try {
                    await api.post(`articles/${article.id}/publish`)
                    void qc.invalidateQueries({ queryKey: articleKey })
                  } catch (err) {
                    setActionError(
                      await extractErrorMessage(err, 'Не удалось опубликовать'),
                    )
                  }
                }}
              >
                Опубликовать
              </Button>
            )}
            {isArchived && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => restoreMutation.mutate()}
                disabled={restoreMutation.isPending}
                data-testid="restore-article-button"
              >
                {restoreMutation.isPending ? 'Восстанавливаем…' : 'Восстановить'}
              </Button>
            )}
            {!isArchived && (
              <DeleteArticleDialog
                articleId={article.id}
                topicId={article.topic_id}
                isAdmin={isAdmin}
              />
            )}
          </>
        )}
        <ShareDropdown title={article.title} />
        {actionError && (
          <p className="w-full text-sm text-destructive" role="alert">
            {actionError}
          </p>
        )}
      </div>

      <AIProposalsPanel articleId={article.id} canManage={canEdit} />

      {accessToken && (
        <div className="text-sm">
          {revisionsCount > 0 ? (
            <Link
              href={`/articles/${article.id}/revisions` as never}
              className="text-primary hover:underline"
              data-testid="revisions-link"
            >
              История правок ({revisionsCount})
            </Link>
          ) : (
            <span className="text-muted-foreground">История правок пуста</span>
          )}
        </div>
      )}

      <AIReviewsSection articleId={article.id} />

      <CommentThread articleId={article.id} />
    </article>
  )
}
