'use client'

import type { JSONContent } from '@tiptap/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles, X } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { DeleteArticleDialog } from '@/components/articles/delete-article-dialog'
import { NotionEditor } from '@/components/editor/notion-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { extractMarkdownFromDoc } from '@/lib/markdown-utils'
import type { ArticleRead, DocContent } from '@/lib/types'
import { articleHref, parseArticleSlugParam } from '@/lib/url-utils'

interface PrefillPayload {
  proposalId: string
  proposedContent: DocContent
}

function readPrefill(articleId: string): PrefillPayload | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(`ai-proposal-prefill:${articleId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as PrefillPayload
    if (!parsed || typeof parsed !== 'object' || !parsed.proposedContent) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function clearPrefill(articleId: string): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.removeItem(`ai-proposal-prefill:${articleId}`)
  } catch {
    /* ignore */
  }
}

export default function ArticleEditPage() {
  const params = useParams<{ articleId: string }>()
  // Accept ``<uuid>`` and ``<uuid>-<slug>`` — see /articles/[articleId]/page.tsx.
  const articleId = parseArticleSlugParam(params.articleId ?? '').uuid
  const router = useRouter()
  const qc = useQueryClient()
  const hydrated = useAuthStore((s) => s.hydrated)
  const accessToken = useAuthStore((s) => s.accessToken)
  const user = useAuthStore((s) => s.user)

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const articleKey = ['article', articleId] as const
  const articleQuery = useQuery({
    queryKey: articleKey,
    queryFn: () => api.get(`articles/${articleId}`).json<ArticleRead>(),
    enabled: Boolean(articleId),
  })

  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [content, setContent] = useState<JSONContent | null>(null)
  const [editReason, setEditReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [hydrationDone, setHydrationDone] = useState(false)
  const [prefill, setPrefill] = useState<PrefillPayload | null>(null)

  // Seed local state from the server once when the article first loads.
  useEffect(() => {
    if (!articleQuery.data || hydrationDone) return
    setTitle(articleQuery.data.title)
    setSummary(articleQuery.data.summary ?? '')
    setContent(articleQuery.data.content as JSONContent)
    setHydrationDone(true)
  }, [articleQuery.data, hydrationDone])

  // Pick up a queued AI-proposal prefill (set by the panel's "Скопировать в
  // редактор" action) on mount. We DO NOT auto-apply it: the user has to
  // click "Вставить в редактор" so they can compare before overwriting.
  useEffect(() => {
    if (!articleId) return
    const payload = readPrefill(articleId)
    if (payload) setPrefill(payload)
  }, [articleId])

  async function applyPrefill() {
    if (!prefill) return
    // LLM proposals today arrive as raw markdown wrapped into a single
    // paragraph node. If we just shove that into ProseMirror, the user
    // sees literal `#`, `**`, `$$…$$`. Instead we copy the markdown to
    // the clipboard so the user can paste (Cmd/Ctrl+V) into the editor —
    // the Markdown TipTap extension (`transformPastedText: true`) will
    // auto-convert it to proper blocks.
    const md = extractMarkdownFromDoc(prefill.proposedContent as JSONContent)
    if (md !== null) {
      try {
        await navigator.clipboard.writeText(md)
        toast.success(
          'Markdown скопирован. Вставьте (Cmd/Ctrl+V) в редактор — он автоматически распарсится.',
        )
      } catch {
        // Clipboard API unavailable (e.g. headless / insecure context) —
        // fall back to dumping the markdown as plain text so the user
        // can at least manually clean it up.
        setContent({
          type: 'doc',
          content: [
            { type: 'paragraph', content: [{ type: 'text', text: md }] },
          ],
        })
        toast.warning(
          'Не удалось скопировать в буфер. Markdown вставлен как текст.',
        )
      }
    } else {
      setContent(prefill.proposedContent as JSONContent)
      toast.success('AI-предложение вставлено в редактор')
    }
    clearPrefill(articleId)
    setPrefill(null)
  }

  function dismissPrefill() {
    clearPrefill(articleId)
    setPrefill(null)
  }

  const article = articleQuery.data

  const isAuthor = Boolean(article && user && article.author.id === user.id)
  const isModOrAdmin = user?.role === 'moderator' || user?.role === 'admin'
  const canEdit = isAuthor || isModOrAdmin
  const requireEditReason = !isAuthor && isModOrAdmin

  const patchMutation = useMutation({
    mutationFn: () =>
      api
        .patch(`articles/${articleId}`, {
          json: {
            title: title || undefined,
            summary: summary || null,
            content,
            ...(requireEditReason && editReason
              ? { edit_reason: editReason }
              : {}),
          },
        })
        .json<ArticleRead>(),
  })

  const publishMutation = useMutation({
    mutationFn: () =>
      api.post(`articles/${articleId}/publish`).json<ArticleRead>(),
  })

  async function saveDraft() {
    setError(null)
    if (!title.trim()) {
      setError('Введите заголовок')
      return
    }
    if (requireEditReason && !editReason.trim()) {
      setError('Укажите причину правки чужой статьи')
      return
    }
    try {
      const updated = await patchMutation.mutateAsync()
      await qc.invalidateQueries({ queryKey: articleKey })
      toast.success('Сохранено')
      router.push(articleHref(updated) as never)
    } catch (err) {
      setError(await extractErrorMessage(err, 'Не удалось сохранить'))
    }
  }

  async function saveAndPublish() {
    setError(null)
    if (!title.trim()) {
      setError('Введите заголовок')
      return
    }
    if (requireEditReason && !editReason.trim()) {
      setError('Укажите причину правки чужой статьи')
      return
    }
    try {
      const updated = await patchMutation.mutateAsync()
      if (article?.status === 'draft') {
        await publishMutation.mutateAsync()
      }
      await qc.invalidateQueries({ queryKey: articleKey })
      toast.success('Опубликовано')
      router.push(articleHref(updated) as never)
    } catch (err) {
      setError(await extractErrorMessage(err, 'Не удалось опубликовать'))
    }
  }

  if (!hydrated || !accessToken) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }
  if (articleQuery.isLoading || !hydrationDone) {
    return <p className="text-muted-foreground">Загружаем статью…</p>
  }
  if (articleQuery.isError || !article) {
    return <p className="text-destructive">Статья не найдена.</p>
  }
  if (!canEdit) {
    return (
      <p className="text-destructive">
        У вас нет прав на редактирование этой статьи.
      </p>
    )
  }

  const submitting = patchMutation.isPending || publishMutation.isPending
  const isDraft = article.status === 'draft'
  const isArchived = article.status === 'archived'
  const isAdmin = user?.role === 'admin'

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">Редактирование статьи</h1>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {isDraft && <Badge variant="secondary">Черновик</Badge>}
          <span>@{article.author.username}</span>
        </div>
      </div>

      {prefill && (
        <div
          data-testid="ai-prefill-banner"
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/40 bg-primary/5 p-3 text-sm"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <span>
              У вас есть AI-предложение для применения. Вставить в редактор?
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={applyPrefill}
              data-testid="ai-prefill-apply"
            >
              Вставить в редактор
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={dismissPrefill}
              data-testid="ai-prefill-dismiss"
              aria-label="Отменить"
            >
              <X className="h-4 w-4" />
              Отменить
            </Button>
          </div>
        </div>
      )}

      <Tabs defaultValue="edit">
        <TabsList>
          <TabsTrigger value="edit" data-testid="tab-edit">
            Редактирование
          </TabsTrigger>
          <TabsTrigger value="preview" data-testid="tab-preview">
            Превью
          </TabsTrigger>
        </TabsList>
        <TabsContent value="edit">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Контент</CardTitle>
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
                  data-testid="article-title"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="summary" className="text-sm font-medium">
                  Краткое описание
                </label>
                <Textarea
                  id="summary"
                  rows={2}
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Содержимое</span>
                <NotionEditor
                  value={content ?? undefined}
                  onChange={setContent}
                  editable
                />
              </div>
              {requireEditReason && (
                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor="edit_reason"
                    className="text-sm font-medium"
                  >
                    Причина правки (обязательно — модератор/админ)
                  </label>
                  <Textarea
                    id="edit_reason"
                    rows={2}
                    value={editReason}
                    onChange={(e) => setEditReason(e.target.value)}
                    placeholder="Например: исправление неточности в формуле"
                    required
                  />
                </div>
              )}
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
                {patchMutation.isPending
                  ? 'Сохраняем…'
                  : 'Сохранить как драфт'}
              </Button>
              <Button
                type="button"
                onClick={saveAndPublish}
                disabled={submitting}
                data-testid="publish-article-button"
              >
                {publishMutation.isPending
                  ? 'Публикуем…'
                  : isDraft
                    ? 'Опубликовать'
                    : 'Сохранить'}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() =>
                  router.push(
                    (article ? articleHref(article) : `/articles/${articleId}`) as never,
                  )
                }
              >
                Отмена
              </Button>
              {!isArchived && (
                <DeleteArticleDialog
                  articleId={article.id}
                  topicId={article.topic_id}
                  isAdmin={isAdmin}
                  size="default"
                />
              )}
            </CardFooter>
          </Card>
        </TabsContent>
        <TabsContent value="preview">
          <article className="flex flex-col gap-4">
            <h2 className="text-3xl font-bold tracking-tight">
              {title || '(без заголовка)'}
            </h2>
            {summary && (
              <p className="text-lg text-muted-foreground">{summary}</p>
            )}
            <NotionEditor
              value={content ?? { type: 'doc', content: [{ type: 'paragraph' }] }}
              editable={false}
            />
          </article>
        </TabsContent>
      </Tabs>
    </div>
  )
}
