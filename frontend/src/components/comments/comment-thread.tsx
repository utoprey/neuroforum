'use client'

import type { JSONContent } from '@tiptap/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, useMemo } from 'react'

import { NotionEditor } from '@/components/editor/notion-editor'
import { ReactionBar } from '@/components/reactions/reaction-bar'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { OnlineDot } from '@/components/user/online-dot'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { cn } from '@/lib/utils'
import type { MessageRead } from '@/lib/types'

const MAX_VISIBLE_DEPTH = 4
const INDENT_PX = 16

const EMPTY_DOC: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
}

export interface CommentThreadProps {
  articleId: string
}

export function CommentThread({ articleId }: CommentThreadProps) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const qc = useQueryClient()

  const listKey = ['article', articleId, 'messages'] as const
  const messagesQuery = useQuery({
    queryKey: listKey,
    queryFn: () =>
      api
        .get(`articles/${articleId}/messages`, {
          searchParams: { limit: 100 },
        })
        .json<MessageRead[]>(),
  })

  const tree = useMemo(
    () => buildTree(messagesQuery.data ?? []),
    [messagesQuery.data],
  )

  const [composing, setComposing] = useState(false)
  const [draft, setDraft] = useState<JSONContent>(EMPTY_DOC)
  const [error, setError] = useState<string | null>(null)

  // Map<messageId, collapsed>. By default all branches are expanded; clicking
  // a "Свернуть"/"N ответов скрыты" toggle flips the boolean for that node.
  const [collapsed, setCollapsed] = useState<Map<string, boolean>>(new Map())
  const toggleCollapse = (id: string) => {
    setCollapsed((prev) => {
      const next = new Map(prev)
      next.set(id, !next.get(id))
      return next
    })
  }

  const postMutation = useMutation({
    mutationFn: (body: { content: JSONContent; parent_id?: string }) =>
      api
        .post(`articles/${articleId}/messages`, { json: body })
        .json<MessageRead>(),
    onSuccess: () => {
      setDraft(EMPTY_DOC)
      setComposing(false)
      void qc.invalidateQueries({ queryKey: listKey })
    },
    onError: async (err) => {
      setError(await extractErrorMessage(err, 'Не удалось отправить комментарий'))
    },
  })

  async function submitTopLevel() {
    setError(null)
    await postMutation.mutateAsync({ content: draft })
  }

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">Комментарии</h2>

      {accessToken ? (
        composing ? (
          <div className="flex flex-col gap-2 rounded-md border border-border p-3">
            <NotionEditor
              value={draft}
              onChange={setDraft}
              editable
              placeholder="Что вы об этом думаете?"
            />
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={submitTopLevel}
                disabled={postMutation.isPending}
                data-testid="submit-comment"
              >
                {postMutation.isPending ? 'Отправляем…' : 'Отправить'}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setComposing(false)
                  setDraft(EMPTY_DOC)
                }}
              >
                Отмена
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setComposing(true)}
            data-testid="open-comment-composer"
            className="self-start"
          >
            Написать комментарий
          </Button>
        )
      ) : (
        <p className="text-sm text-muted-foreground">
          Войдите, чтобы оставить комментарий.
        </p>
      )}

      {messagesQuery.isLoading && (
        <p className="text-muted-foreground">Загружаем комментарии…</p>
      )}
      {messagesQuery.isError && (
        <p className="text-destructive">Не удалось загрузить комментарии.</p>
      )}
      {messagesQuery.data && messagesQuery.data.length === 0 && (
        <p className="text-muted-foreground">Будьте первым!</p>
      )}

      <ul className="flex flex-col gap-3">
        {tree.roots.map((m) => (
          <li key={m.id}>
            <CommentNode
              message={m}
              tree={tree}
              articleId={articleId}
              invalidateKey={listKey}
              collapsed={collapsed}
              onToggleCollapse={toggleCollapse}
              effectiveDepth={0}
            />
          </li>
        ))}
      </ul>
    </section>
  )
}

interface MessageTree {
  byId: Map<string, MessageRead>
  childrenOf: Map<string, MessageRead[]>
  roots: MessageRead[]
}

function buildTree(messages: MessageRead[]): MessageTree {
  const byId = new Map<string, MessageRead>()
  const childrenOf = new Map<string, MessageRead[]>()
  for (const m of messages) byId.set(m.id, m)
  for (const m of messages) {
    if (m.parent_id && byId.has(m.parent_id)) {
      const arr = childrenOf.get(m.parent_id) ?? []
      arr.push(m)
      childrenOf.set(m.parent_id, arr)
    }
  }
  // Sort children chronologically for stable rendering.
  for (const arr of childrenOf.values()) {
    arr.sort((a, b) => a.created_at.localeCompare(b.created_at))
  }
  const roots = messages
    .filter((m) => !m.parent_id || !byId.has(m.parent_id))
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
  return { byId, childrenOf, roots }
}

interface CommentNodeProps {
  message: MessageRead
  tree: MessageTree
  articleId: string
  invalidateKey: readonly unknown[]
  collapsed: Map<string, boolean>
  onToggleCollapse: (id: string) => void
  /**
   * Local depth used for indentation. Capped at MAX_VISIBLE_DEPTH so very
   * deep threads stay readable on narrow screens.
   */
  effectiveDepth: number
}

function CommentNode({
  message,
  tree,
  articleId,
  invalidateKey,
  collapsed,
  onToggleCollapse,
  effectiveDepth,
}: CommentNodeProps) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const qc = useQueryClient()
  const [replying, setReplying] = useState(false)
  const [draft, setDraft] = useState<JSONContent>(EMPTY_DOC)
  const [error, setError] = useState<string | null>(null)

  const replyMutation = useMutation({
    mutationFn: () =>
      api
        .post(`articles/${articleId}/messages`, {
          json: { content: draft, parent_id: message.id },
        })
        .json<MessageRead>(),
    onSuccess: () => {
      setDraft(EMPTY_DOC)
      setReplying(false)
      void qc.invalidateQueries({ queryKey: invalidateKey })
    },
    onError: async (err) => {
      setError(await extractErrorMessage(err, 'Не удалось ответить'))
    },
  })

  const children = tree.childrenOf.get(message.id) ?? []
  const indent = Math.min(effectiveDepth, MAX_VISIBLE_DEPTH) * INDENT_PX
  const isRedacted =
    message.status === 'deleted_by_author' ||
    message.status === 'hidden_by_mod'
  const isCollapsed = collapsed.get(message.id) === true
  const hasChildren = children.length > 0
  // Threaded look: every reply (depth > 0) gets a left rail.
  const hasRail = effectiveDepth > 0

  return (
    <div style={{ marginLeft: indent }} className="flex flex-col gap-2">
      <article
        className={cn(
          'flex gap-3 rounded-md border border-border p-3 transition-colors',
          hasRail && 'border-l-2 hover:border-l-primary',
        )}
      >
        <div className="relative shrink-0">
          <Avatar className="h-8 w-8">
            {message.author.avatar_url ? (
              <AvatarImage
                src={message.author.avatar_url}
                alt={message.author.username}
              />
            ) : null}
            <AvatarFallback>{message.author.username[0]}</AvatarFallback>
          </Avatar>
          <OnlineDot isOnline={message.author.is_online} />
        </div>
        <div className="flex flex-1 flex-col gap-1.5">
          <header className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">@{message.author.username}</span>
            <span className="text-muted-foreground">
              {new Date(message.created_at).toLocaleString('ru')}
            </span>
            {message.status === 'edited' && (
              <span className="text-xs text-muted-foreground">(изменено)</span>
            )}
          </header>
          {isRedacted ? (
            <div className="italic text-muted-foreground">
              {message.placeholder ??
                (message.status === 'deleted_by_author'
                  ? 'Сообщение удалено автором'
                  : 'Скрыто модератором')}
            </div>
          ) : (
            <NotionEditor value={message.content ?? EMPTY_DOC} editable={false} />
          )}
          <div className="flex flex-wrap items-center gap-3">
            <ReactionBar
              scope="messages"
              parentId={message.id}
              counts={message.reaction_counts}
              invalidateKey={invalidateKey}
            />
            {accessToken && !isRedacted && message.depth < 8 && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setReplying((v) => !v)}
              >
                {replying ? 'Отмена' : 'Ответить'}
              </Button>
            )}
            {hasChildren && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => onToggleCollapse(message.id)}
                aria-expanded={!isCollapsed}
                data-testid={`collapse-${message.id}`}
                className="gap-1"
              >
                {isCollapsed ? (
                  <>
                    <ChevronRight className="h-4 w-4" />
                    {children.length} ответ
                    {pluralEnding(children.length)} скрыт
                    {children.length === 1 ? '' : 'о'}
                  </>
                ) : (
                  <>
                    <ChevronDown className="h-4 w-4" />
                    Свернуть
                  </>
                )}
              </Button>
            )}
          </div>
          {replying && (
            <div className="mt-2 flex flex-col gap-2 rounded-md border border-border p-2">
              <NotionEditor value={draft} onChange={setDraft} editable />
              {error && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => replyMutation.mutate()}
                  disabled={replyMutation.isPending}
                >
                  {replyMutation.isPending ? 'Отправляем…' : 'Ответить'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </article>

      {hasChildren && !isCollapsed && (
        <div className="flex flex-col gap-2">
          {children.map((c) => (
            <CommentNode
              key={c.id}
              message={c}
              tree={tree}
              articleId={articleId}
              invalidateKey={invalidateKey}
              collapsed={collapsed}
              onToggleCollapse={onToggleCollapse}
              effectiveDepth={effectiveDepth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function pluralEnding(n: number): string {
  // 1 → '', 2-4 → 'а', 5+ → 'ов'
  const m = n % 10
  const t = n % 100
  if (t >= 11 && t <= 14) return 'ов'
  if (m === 1) return ''
  if (m >= 2 && m <= 4) return 'а'
  return 'ов'
}
