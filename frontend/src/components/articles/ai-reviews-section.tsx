'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { JSONContent } from '@tiptap/react'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { MarkdownContent } from '@/components/editor/markdown-content'
import { NotionEditor } from '@/components/editor/notion-editor'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { extractMarkdownFromDoc, markdownToDoc } from '@/lib/markdown-utils'
import { formatRelative } from '@/lib/notifications'
import { AI_PROPOSAL_ACTION_LABEL, type ArticleAIProposal } from '@/lib/types'

/**
 * "🤖 AI обзоры" — read-only feed of accepted AI proposals attached to an
 * article. Lives between the article body and the comment thread so a casual
 * reader can browse the curated AI take without diving into the management
 * panel above (which is only useful to the author / moderators).
 *
 * Empty / error states render nothing on purpose — the section should not
 * advertise itself to readers when there is no curated content yet, and a
 * 403 (backend currently restricts listing to author/mod/admin — see TODO in
 * the agent report) should fail quietly so a regular reader's article page
 * is not littered with red error blobs.
 */

interface Props {
  articleId: string
}

/** Loose shape for proposals that may carry an llm_meta blob in `context`. */
type ProposalWithMeta = ArticleAIProposal & {
  llm_meta?: { model?: string } | null
}

export function AIReviewsSection({ articleId }: Props) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const user = useAuthStore((s) => s.user)
  const qc = useQueryClient()
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  // editing[proposalId] === undefined → read mode; else string is the draft md.
  const [editing, setEditing] = useState<Record<string, string>>({})

  const enterEdit = (id: string, initial: string) =>
    setEditing((s) => ({ ...s, [id]: initial }))
  const exitEdit = (id: string) =>
    setEditing((s) => {
      const next = { ...s }
      delete next[id]
      return next
    })

  const query = useQuery({
    queryKey: ['article', articleId, 'ai-proposals', 'accepted'] as const,
    queryFn: () =>
      api
        .get(`articles/${articleId}/ai-proposals`, {
          searchParams: { status: 'accepted' },
        })
        .json<ArticleAIProposal[]>(),
    // Backend requires auth on this endpoint, so we skip the call entirely
    // for guests. (And — see TODO — the backend currently 403s for non
    // author/mod/admin too; the section just stays empty for those readers.)
    enabled: Boolean(articleId && accessToken),
  })

  const saveMutation = useMutation({
    mutationFn: async ({ id, md }: { id: string; md: string }) => {
      const doc = markdownToDoc(md)
      await api
        .patch(`ai-proposals/${id}`, { json: { proposed_content: doc } })
        .json<ArticleAIProposal>()
      return id
    },
    onSuccess: async (id) => {
      toast.success('Сохранено')
      exitEdit(id)
      await Promise.all([
        qc.invalidateQueries({
          queryKey: ['article', articleId, 'ai-proposals', 'accepted'],
        }),
        qc.invalidateQueries({
          queryKey: ['article', articleId, 'ai-proposals'],
        }),
      ])
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  if (!accessToken) return null
  if (query.isLoading) return null
  if (query.isError || !query.data || query.data.length === 0) return null

  const proposals = query.data
  const canEdit = (p: ArticleAIProposal) =>
    Boolean(
      user &&
        (p.requested_by.id === user.id ||
          user.role === 'moderator' ||
          user.role === 'admin'),
    )

  return (
    <section
      className="my-8 rounded-lg border border-border bg-muted/30 p-4"
      data-testid="ai-reviews-section"
      aria-label="AI обзоры"
    >
      <h2 className="mb-4 flex items-center gap-2 text-xl font-semibold">
        <Sparkles className="h-5 w-5 text-primary" />
        AI обзоры
        <Badge variant="outline" className="ml-2">
          {proposals.length}
        </Badge>
      </h2>
      <div className="space-y-4">
        {proposals.map((p) => {
          const isCollapsed = collapsed[p.id] === true
          const meta = (p as ProposalWithMeta).llm_meta ?? null
          const md = extractMarkdownFromDoc(
            p.proposed_content as unknown as JSONContent,
          )
          const inEdit = editing[p.id] !== undefined
          const editText = editing[p.id] ?? ''
          const showEditButton = canEdit(p)
          // For editing we need a markdown blob to seed the textarea. If the
          // current doc isn't simple-markdown-shaped, fall back to a JSON
          // dump so the user at least sees what they're editing — they can
          // replace it wholesale with new markdown.
          const seedText =
            md ??
            JSON.stringify(p.proposed_content, null, 2)
          return (
            <div
              key={p.id}
              className="rounded-md border bg-background p-3"
              data-testid="ai-review-item"
              data-proposal-id={p.id}
            >
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                <Avatar className="h-6 w-6">
                  {p.requested_by.avatar_url ? (
                    <AvatarImage
                      src={p.requested_by.avatar_url}
                      alt={p.requested_by.username}
                    />
                  ) : null}
                  <AvatarFallback>
                    {p.requested_by.username[0]?.toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <span>@{p.requested_by.username}</span>
                <Badge variant="secondary" className="text-xs">
                  {AI_PROPOSAL_ACTION_LABEL[p.action] ?? p.action}
                </Badge>
                {meta?.model && (
                  <span className="text-xs text-muted-foreground">
                    {String(meta.model)}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {formatRelative(p.created_at)}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  {showEditButton && !inEdit && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => enterEdit(p.id, seedText)}
                      data-testid="ai-review-edit"
                    >
                      Редактировать
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setCollapsed((s) => ({ ...s, [p.id]: !s[p.id] }))
                    }
                    data-testid="ai-review-toggle"
                  >
                    {isCollapsed ? 'Показать' : 'Скрыть'}
                  </Button>
                </div>
              </div>
              {!isCollapsed && (
                <div data-testid="ai-review-content">
                  {inEdit ? (
                    <div className="space-y-2">
                      <Textarea
                        value={editText}
                        onChange={(e) =>
                          setEditing((s) => ({
                            ...s,
                            [p.id]: e.target.value,
                          }))
                        }
                        rows={Math.max(6, editText.split('\n').length + 1)}
                        className="font-mono text-sm"
                        data-testid="ai-review-edit-textarea"
                      />
                      <div className="rounded-md border bg-muted/30 p-2">
                        <p className="mb-1 text-xs text-muted-foreground">
                          Превью:
                        </p>
                        <MarkdownContent markdown={editText} />
                      </div>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() =>
                            saveMutation.mutate({
                              id: p.id,
                              md: editText,
                            })
                          }
                          disabled={saveMutation.isPending}
                          data-testid="ai-review-edit-save"
                        >
                          {saveMutation.isPending
                            ? 'Сохраняем…'
                            : 'Сохранить'}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => exitEdit(p.id)}
                          data-testid="ai-review-edit-cancel"
                        >
                          Отмена
                        </Button>
                      </div>
                    </div>
                  ) : md !== null ? (
                    <MarkdownContent markdown={md} />
                  ) : (
                    <NotionEditor
                      value={p.proposed_content as unknown as JSONContent}
                      editable={false}
                    />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
