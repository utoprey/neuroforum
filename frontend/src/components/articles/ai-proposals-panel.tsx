'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Sparkles } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { MarkdownContent } from '@/components/editor/markdown-content'
import { NotionEditor } from '@/components/editor/notion-editor'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type { JSONContent } from '@tiptap/react'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { extractMarkdownFromDoc, markdownToDoc } from '@/lib/markdown-utils'
import { formatRelative } from '@/lib/notifications'
import {
  AI_PROPOSAL_ACTION_LABEL,
  type AIProposalStatus,
  type ArticleAIProposal,
} from '@/lib/types'

interface Props {
  articleId: string
  /** Whether the current viewer can accept/reject proposals (author/mod/admin). */
  canManage: boolean
}

type FilterValue = 'active' | 'history' | 'all'

const HISTORY_STATUSES: AIProposalStatus[] = ['accepted', 'rejected', 'expired']

function statusFilterParam(filter: FilterValue): string | undefined {
  // "active" → pending only. "history" / "all" → no single filter, we fetch
  // everything and post-filter client-side so we can show mixed lists without
  // multiple round trips.
  return filter === 'active' ? 'pending' : undefined
}

function applyClientFilter(
  rows: ArticleAIProposal[],
  filter: FilterValue,
): ArticleAIProposal[] {
  if (filter === 'history') {
    return rows.filter((p) => HISTORY_STATUSES.includes(p.status))
  }
  return rows
}

/**
 * Stack of AI proposal cards rendered alongside an article. Pure annotation
 * surface — accepting a proposal flips its status to `accepted` ("полезно"),
 * but never modifies the article body. The author can copy the proposal text
 * into the editor via "Скопировать в редактор".
 */
export function AIProposalsPanel({ articleId, canManage }: Props) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<FilterValue>('active')
  const proposalsKey = [
    'article',
    articleId,
    'ai-proposals',
    filter,
  ] as const

  const proposalsQuery = useQuery({
    queryKey: proposalsKey,
    queryFn: () => {
      const param = statusFilterParam(filter)
      return api
        .get(`articles/${articleId}/ai-proposals`, {
          searchParams: param ? { status: param } : undefined,
        })
        .json<ArticleAIProposal[]>()
    },
    enabled: Boolean(articleId),
    refetchInterval: 30_000,
  })

  const rows = proposalsQuery.data ?? []
  const visible = applyClientFilter(rows, filter)

  return (
    <section
      className="flex flex-col gap-3"
      aria-label="AI-предложения"
      data-testid="ai-proposals-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-lg font-semibold">AI-предложения</h2>
        </div>
        <Tabs
          value={filter}
          onValueChange={(v) => setFilter(v as FilterValue)}
        >
          <TabsList data-testid="ai-proposals-filter">
            <TabsTrigger value="active" data-testid="ai-proposals-filter-active">
              Активные
            </TabsTrigger>
            <TabsTrigger value="all" data-testid="ai-proposals-filter-all">
              Все
            </TabsTrigger>
            <TabsTrigger
              value="history"
              data-testid="ai-proposals-filter-history"
            >
              История
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filter === 'active'
            ? 'Нет активных предложений.'
            : 'Здесь пока пусто.'}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {visible.map((p) => (
            <ProposalCard
              key={p.id}
              articleId={articleId}
              proposal={p}
              canManage={canManage}
              onChanged={async () => {
                await Promise.all([
                  qc.invalidateQueries({
                    queryKey: ['article', articleId, 'ai-proposals'],
                  }),
                  // The accepted list lives in a sibling section ("AI обзоры")
                  // and uses its own query key — invalidate it explicitly so a
                  // freshly-accepted proposal appears there without a reload.
                  qc.invalidateQueries({
                    queryKey: ['article', articleId, 'ai-proposals', 'accepted'],
                  }),
                  qc.invalidateQueries({ queryKey: ['article', articleId] }),
                ])
              }}
            />
          ))}
        </div>
      )}
    </section>
  )
}

const STATUS_BADGE_VARIANT: Record<
  AIProposalStatus,
  'default' | 'secondary' | 'destructive' | 'outline'
> = {
  pending: 'secondary',
  accepted: 'default',
  rejected: 'destructive',
  expired: 'outline',
}

const STATUS_LABEL: Record<AIProposalStatus, string> = {
  pending: 'pending',
  accepted: 'полезно',
  rejected: 'отклонено',
  expired: 'истекло',
}

function ProposalCard({
  articleId,
  proposal,
  canManage,
  onChanged,
}: {
  articleId: string
  proposal: ArticleAIProposal
  canManage: boolean
  onChanged: () => Promise<void> | void
}) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')
  // undefined → read mode; string → current draft markdown.
  const [editDraft, setEditDraft] = useState<string | undefined>(undefined)
  const inEdit = editDraft !== undefined

  const canEdit = Boolean(
    user &&
      (proposal.requested_by.id === user.id ||
        user.role === 'moderator' ||
        user.role === 'admin'),
  )

  const saveEditMutation = useMutation({
    mutationFn: async (md: string) => {
      const doc = markdownToDoc(md)
      await api
        .patch(`ai-proposals/${proposal.id}`, {
          json: { proposed_content: doc },
        })
        .json<ArticleAIProposal>()
    },
    onSuccess: async () => {
      toast.success('Сохранено')
      setEditDraft(undefined)
      await onChanged()
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  const acceptMutation = useMutation({
    mutationFn: () =>
      api
        .post(`ai-proposals/${proposal.id}/accept`)
        .json<ArticleAIProposal>(),
    onSuccess: async () => {
      toast.success('Опубликовано в AI обзоры')
      await onChanged()
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось опубликовать'))
    },
  })

  const rejectMutation = useMutation({
    mutationFn: async () => {
      await api.post(`ai-proposals/${proposal.id}/reject`, {
        json: { action: 'reject', reason: reason.trim() || null },
      })
    },
    onSuccess: async () => {
      toast.success('Отклонено')
      setRejectOpen(false)
      setReason('')
      await onChanged()
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось отклонить'))
    },
  })

  const submitting =
    acceptMutation.isPending || rejectMutation.isPending
  const requester = proposal.requested_by
  const isPending = proposal.status === 'pending'
  const showManageActions = canManage && isPending

  // `proposed_content` is wire-typed as DocContent — the editor expects a
  // TipTap JSONContent which is structurally identical at this depth.
  const content = proposal.proposed_content as unknown as JSONContent
  // Today's LLM pipeline returns raw markdown wrapped in a single
  // paragraph; detect that shape and render via `MarkdownContent` so
  // headings / math / code blocks are formatted instead of shown as
  // literal `#`, `**`, `$$…$$` text.
  const markdown = extractMarkdownFromDoc(content)

  function copyToEditor() {
    if (typeof window === 'undefined') return
    try {
      sessionStorage.setItem(
        `ai-proposal-prefill:${articleId}`,
        JSON.stringify({
          proposalId: proposal.id,
          proposedContent: proposal.proposed_content,
        }),
      )
    } catch {
      // sessionStorage can throw on private-mode quotas; fall back to
      // navigating anyway so the user at least lands on the edit page.
    }
    router.push(
      `/articles/${articleId}/edit?proposal=${proposal.id}` as never,
    )
  }

  return (
    <Card data-testid="ai-proposal-card" data-proposal-id={proposal.id}>
      <CardHeader className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-col gap-1">
            <h3 className="text-base font-semibold">
              AI предлагает: {AI_PROPOSAL_ACTION_LABEL[proposal.action]}
            </h3>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge
                variant={STATUS_BADGE_VARIANT[proposal.status]}
                data-testid="ai-proposal-status"
              >
                {STATUS_LABEL[proposal.status]}
              </Badge>
              <span className="flex items-center gap-1.5">
                <Avatar className="h-5 w-5">
                  {requester.avatar_url ? (
                    <AvatarImage
                      src={requester.avatar_url}
                      alt={requester.username}
                    />
                  ) : null}
                  <AvatarFallback>
                    {requester.username[0]?.toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                @{requester.username}
              </span>
              <span>{formatRelative(proposal.created_at)}</span>
              {proposal.decided_at && (
                <span>
                  — решено {formatRelative(proposal.decided_at)}
                  {proposal.decided_by ? ` (@${proposal.decided_by.username})` : ''}
                </span>
              )}
            </div>
          </div>
        </div>
        {proposal.prompt && (
          <p className="text-sm italic text-muted-foreground">
            «{proposal.prompt}»
          </p>
        )}
      </CardHeader>
      <CardContent>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          {inEdit ? (
            <div className="space-y-2">
              <Textarea
                value={editDraft ?? ''}
                onChange={(e) => setEditDraft(e.target.value)}
                rows={Math.max(6, (editDraft ?? '').split('\n').length + 1)}
                className="font-mono text-sm"
                data-testid="ai-proposal-edit-textarea"
              />
              <div className="rounded-md border bg-background p-2">
                <p className="mb-1 text-xs text-muted-foreground">Превью:</p>
                <MarkdownContent markdown={editDraft ?? ''} />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() =>
                    saveEditMutation.mutate(editDraft ?? '')
                  }
                  disabled={saveEditMutation.isPending}
                  data-testid="ai-proposal-edit-save"
                >
                  {saveEditMutation.isPending ? 'Сохраняем…' : 'Сохранить'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setEditDraft(undefined)}
                  data-testid="ai-proposal-edit-cancel"
                >
                  Отмена
                </Button>
              </div>
            </div>
          ) : markdown !== null ? (
            <MarkdownContent markdown={markdown} />
          ) : (
            <NotionEditor value={content} editable={false} />
          )}
        </div>
      </CardContent>
      {!inEdit && (showManageActions || canEdit) && (
        <CardFooter className="flex flex-wrap gap-2">
          {showManageActions && (
            <>
              <Button
                type="button"
                onClick={() => acceptMutation.mutate()}
                disabled={submitting}
                data-testid="ai-proposal-accept"
              >
                <Sparkles className="mr-2 h-4 w-4" />
                {acceptMutation.isPending
                  ? 'Публикуем…'
                  : 'Опубликовать в AI обзоры'}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={copyToEditor}
                disabled={submitting}
                data-testid="ai-proposal-copy-to-editor"
              >
                <Copy className="h-4 w-4" />
                Скопировать в редактор
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setRejectOpen(true)}
                disabled={submitting}
                data-testid="ai-proposal-reject"
              >
                Отклонить
              </Button>
            </>
          )}
          {canEdit && (
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                setEditDraft(
                  markdown ??
                    JSON.stringify(proposal.proposed_content, null, 2),
                )
              }
              disabled={submitting}
              data-testid="ai-proposal-edit"
            >
              Редактировать
            </Button>
          )}
        </CardFooter>
      )}

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Отклонить предложение?</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="reject-reason" className="text-sm font-medium">
              Причина (опц.)
            </label>
            <Textarea
              id="reject-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Например: не подходит по стилю"
            />
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setRejectOpen(false)}
              disabled={rejectMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              data-testid="ai-proposal-reject-confirm"
            >
              {rejectMutation.isPending ? 'Отклоняем…' : 'Отклонить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
