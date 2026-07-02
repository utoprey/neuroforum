'use client'

import type { JSONContent } from '@tiptap/react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { NotionEditor } from '@/components/editor/notion-editor'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import type { ArticleRead, TopicRead } from '@/lib/types'
import { articleHref } from '@/lib/url-utils'

const EMPTY_DOC: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
}

/**
 * Slug-based new-article form. Resolves the topic id by
 * (sectionSlug, topicSlug) and then reuses the UUID-based create endpoint
 * (POST /topics/<topic_id>/articles) — the slug-based article URL is
 * built client-side via :func:`articleHref`.
 */
export default function NewArticleBySlugPage() {
  const params = useParams<{ sectionSlug: string; topicSlug: string }>()
  const sectionSlug = params.sectionSlug
  const topicSlug = params.topicSlug
  const router = useRouter()
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)

  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [content, setContent] = useState<JSONContent>(EMPTY_DOC)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const topicQuery = useQuery({
    queryKey: ['topic-by-slug', sectionSlug, topicSlug],
    queryFn: () =>
      api
        .get(`sections/${sectionSlug}/topics/${topicSlug}`)
        .json<TopicRead>(),
    enabled: Boolean(sectionSlug && topicSlug),
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const topicId = topicQuery.data?.id
      if (!topicId) {
        throw new Error('Тема ещё загружается, попробуйте снова')
      }
      return api
        .post(`topics/${topicId}/articles`, {
          json: {
            title,
            summary: summary || null,
            content,
          },
        })
        .json<ArticleRead>()
    },
  })

  const publishMutation = useMutation({
    mutationFn: (articleId: string) =>
      api.post(`articles/${articleId}/publish`).json<ArticleRead>(),
  })

  async function saveDraft() {
    setError(null)
    if (!title.trim()) {
      setError('Введите заголовок')
      return
    }
    try {
      const article = await createMutation.mutateAsync()
      router.push(articleHref(article) as never)
    } catch (err) {
      setError(await extractErrorMessage(err, 'Не удалось сохранить черновик'))
    }
  }

  async function saveAndPublish() {
    setError(null)
    if (!title.trim()) {
      setError('Введите заголовок')
      return
    }
    try {
      const article = await createMutation.mutateAsync()
      await publishMutation.mutateAsync(article.id)
      router.push(articleHref(article) as never)
    } catch (err) {
      setError(await extractErrorMessage(err, 'Не удалось опубликовать'))
    }
  }

  const submitting = createMutation.isPending || publishMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Новая статья</CardTitle>
          <CardDescription>
            Введите заголовок и контент в Notion-стиле. Можно сохранить черновик
            или сразу опубликовать.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="title" className="text-sm font-medium">
              Заголовок
            </label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Например: GLM-пайплайн на BIDS"
              required
              data-testid="article-title"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="summary" className="text-sm font-medium">
              Краткое описание (для ленты)
            </label>
            <Textarea
              id="summary"
              rows={2}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Один-два предложения"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Содержимое</span>
            <NotionEditor
              value={content}
              onChange={setContent}
              editable
              placeholder="Начните писать…"
            />
          </div>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
        </CardContent>
        <CardFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={saveDraft}
            disabled={submitting || !topicQuery.data}
          >
            {createMutation.isPending ? 'Сохраняем…' : 'Сохранить черновик'}
          </Button>
          <Button
            type="button"
            onClick={saveAndPublish}
            disabled={submitting || !topicQuery.data}
            data-testid="publish-article-button"
          >
            {publishMutation.isPending
              ? 'Публикуем…'
              : 'Опубликовать'}
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
