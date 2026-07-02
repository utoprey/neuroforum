'use client'

import type { JSONContent } from '@tiptap/react'
import { useMutation } from '@tanstack/react-query'
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
import type { ArticleRead } from '@/lib/types'

const EMPTY_DOC: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
}

export default function NewArticlePage() {
  const params = useParams<{ topicId: string }>()
  const topicId = params.topicId
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

  const createMutation = useMutation({
    mutationFn: () =>
      api
        .post(`topics/${topicId}/articles`, {
          json: {
            title,
            summary: summary || null,
            content,
          },
        })
        .json<ArticleRead>(),
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
      router.push(`/articles/${article.id}` as never)
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
      router.push(`/articles/${article.id}` as never)
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
            disabled={submitting}
          >
            {createMutation.isPending ? 'Сохраняем…' : 'Сохранить черновик'}
          </Button>
          <Button
            type="button"
            onClick={saveAndPublish}
            disabled={submitting}
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
