'use client'

import type { JSONContent } from '@tiptap/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { toast } from 'sonner'

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { OnlineDot } from '@/components/user/online-dot'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { cn } from '@/lib/utils'
import type {
  ConversationRead,
  DirectMessageRead,
} from '@/lib/types'

const EMPTY_DOC: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
}

/** Build a minimal ProseMirror doc with a single paragraph of text. Empty
 *  string -> empty paragraph (still a valid doc). */
function textToDoc(text: string): JSONContent {
  const trimmed = text.replace(/\r\n/g, '\n')
  if (!trimmed) return EMPTY_DOC
  const lines = trimmed.split('\n')
  return {
    type: 'doc',
    content: lines.map((line) =>
      line.length === 0
        ? { type: 'paragraph' }
        : {
            type: 'paragraph',
            content: [{ type: 'text', text: line }],
          },
    ),
  }
}

/** Recursively pull plain text out of a ProseMirror doc — used for the
 *  inline single-line preview and edit-mode pre-population. */
function docToText(content: JSONContent | null | undefined): string {
  if (!content) return ''
  const lines: string[] = []
  function walkBlock(node: JSONContent): string {
    if (node.type === 'text') return (node.text as string) ?? ''
    const children = (node.content as JSONContent[] | undefined) ?? []
    return children.map(walkBlock).join('')
  }
  const topLevel = (content.content as JSONContent[] | undefined) ?? []
  if (topLevel.length === 0 && content.type !== 'doc') {
    return walkBlock(content)
  }
  for (const block of topLevel) {
    lines.push(walkBlock(block))
  }
  return lines.join('\n')
}

export default function ConversationPage() {
  const params = useParams<{ conversationId: string }>()
  const conversationId = params.conversationId
  const router = useRouter()
  const qc = useQueryClient()
  const me = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const hydrated = useAuthStore((s) => s.hydrated)
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    if (hydrated && !accessToken) router.replace('/login')
  }, [hydrated, accessToken, router])

  const conversationsQuery = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api.get('conversations').json<ConversationRead[]>(),
    enabled: Boolean(accessToken),
  })
  const conversation = conversationsQuery.data?.find(
    (c) => c.id === conversationId,
  )

  const messagesKey = ['conversation', conversationId, 'messages'] as const
  const messagesQuery = useQuery({
    queryKey: messagesKey,
    queryFn: () =>
      api
        .get(`conversations/${conversationId}/messages`, {
          searchParams: { limit: 100 },
        })
        .json<DirectMessageRead[]>(),
    enabled: Boolean(conversationId && accessToken),
    refetchInterval: 5_000,
  })

  // Chronological ordering: oldest first, newest at the bottom.
  const ordered = useMemo(() => {
    const list = messagesQuery.data ?? []
    return [...list].sort((a, b) => a.created_at.localeCompare(b.created_at))
  }, [messagesQuery.data])

  // Auto mark-read whenever new messages arrive while we're on the page.
  useEffect(() => {
    if (!conversationId || !accessToken) return
    if (ordered.length === 0) return
    void api
      .post(`conversations/${conversationId}/mark-read`)
      .catch(() => {
        /* best-effort */
      })
      .finally(() => {
        void qc.invalidateQueries({ queryKey: ['conversations'] })
        void qc.invalidateQueries({ queryKey: ['dm-unread-total'] })
      })
  }, [conversationId, accessToken, ordered.length, qc])

  // Stick to the bottom when the conversation grows or first loads.
  useLayoutEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [ordered.length])

  // Initial jump-to-bottom without smooth animation on first paint.
  useLayoutEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [])

  const autoSize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxRows = 5
    const lineHeight = 20
    const maxHeight = lineHeight * maxRows + 16
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [])

  useEffect(() => {
    autoSize()
  }, [draft, autoSize])

  const sendMutation = useMutation({
    mutationFn: (payload: { content: JSONContent }) =>
      api
        .post(`conversations/${conversationId}/messages`, {
          json: payload,
        })
        .json<DirectMessageRead>(),
    onSuccess: () => {
      setDraft('')
      void qc.invalidateQueries({ queryKey: messagesKey })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось отправить'))
    },
  })

  function submit() {
    const text = draft.trim()
    if (!text || sendMutation.isPending) return
    sendMutation.mutate({ content: textToDoc(draft) })
  }

  if (!hydrated || !accessToken) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }

  const other =
    conversation?.participants.find((p) => p.id !== me?.id) ??
    conversation?.participants[0]

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <Link
          href={'/dm' as never}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← к диалогам
        </Link>
        {other && (
          <Link
            href={`/users/${other.username}` as never}
            className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-accent"
          >
            <div className="relative">
              <Avatar className="h-8 w-8">
                {other.avatar_url ? (
                  <AvatarImage src={other.avatar_url} alt={other.username} />
                ) : null}
                <AvatarFallback>{other.username[0].toUpperCase()}</AvatarFallback>
              </Avatar>
              <OnlineDot isOnline={other.is_online} />
            </div>
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-medium">
                {other.display_name || `@${other.username}`}
              </span>
              {other.is_online && (
                <span className="text-[11px] text-emerald-500">в сети</span>
              )}
            </div>
          </Link>
        )}
      </div>

      <div
        ref={scrollRef}
        className="flex flex-1 flex-col gap-1.5 overflow-y-auto rounded-md border border-border bg-background px-3 py-2"
      >
        {messagesQuery.isLoading && (
          <p className="text-muted-foreground">Загружаем сообщения…</p>
        )}
        {!messagesQuery.isLoading && ordered.length === 0 && (
          <p className="text-muted-foreground">Сообщений пока нет.</p>
        )}
        {ordered.map((m, idx) => {
          const prev = idx > 0 ? ordered[idx - 1] : null
          // Group bubbles from the same author within ~2 minutes to mimic
          // a messenger feed (hide repeated meta/avatar).
          const sameAuthor = prev && prev.author.id === m.author.id
          const closeInTime =
            prev &&
            new Date(m.created_at).getTime() -
              new Date(prev.created_at).getTime() <
              2 * 60_000
          const grouped = Boolean(sameAuthor && closeInTime)
          return (
            <MessageBubble
              key={m.id}
              message={m}
              isMine={m.author.id === me?.id}
              conversationId={conversationId}
              invalidateKey={messagesKey}
              grouped={grouped}
            />
          )
        })}
        <div ref={bottomRef} />
      </div>

      <div className="flex items-end gap-2 rounded-md border border-border bg-background p-2">
        <textarea
          ref={textareaRef}
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="Напишите сообщение… (Enter — отправить, Shift+Enter — перенос)"
          aria-label="Сообщение"
          data-testid="dm-input"
          className="min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm leading-5 outline-none placeholder:text-muted-foreground"
        />
        <Button
          type="button"
          size="sm"
          onClick={submit}
          disabled={sendMutation.isPending || !draft.trim()}
          data-testid="dm-send-button"
        >
          {sendMutation.isPending ? 'Отправляем…' : 'Отправить'}
        </Button>
      </div>
    </div>
  )
}

function MessageBubble({
  message,
  isMine,
  conversationId,
  invalidateKey,
  grouped,
}: {
  message: DirectMessageRead
  isMine: boolean
  conversationId: string
  invalidateKey: readonly unknown[]
  grouped: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editDraft, setEditDraft] = useState<string>(() =>
    docToText(message.content),
  )

  // Unused conversationId silences linter warnings but documents the relationship.
  void conversationId

  const editMutation = useMutation({
    mutationFn: () =>
      api
        .patch(`messages/dm/${message.id}`, {
          json: { content: textToDoc(editDraft) },
        })
        .json<DirectMessageRead>(),
    onSuccess: () => {
      setEditing(false)
      void qc.invalidateQueries({ queryKey: invalidateKey })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () =>
      api.delete(`messages/dm/${message.id}`).then(() => undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: invalidateKey })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось удалить'))
    },
  })

  const isDeleted =
    message.status === 'deleted_by_author' || message.status === 'hidden_by_mod'
  const created = new Date(message.created_at)
  const time = created.toLocaleTimeString('ru', {
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <div
      className={cn(
        'flex items-end gap-2',
        isMine ? 'justify-end' : 'justify-start',
        grouped ? 'mt-0.5' : 'mt-1.5',
      )}
    >
      {!isMine && (
        <div className={cn('w-7 shrink-0', grouped && 'invisible')}>
          {!grouped && (
            <div className="relative">
              <Avatar className="h-7 w-7">
                {message.author.avatar_url ? (
                  <AvatarImage
                    src={message.author.avatar_url}
                    alt={message.author.username}
                  />
                ) : null}
                <AvatarFallback className="text-xs">
                  {message.author.username[0].toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <OnlineDot isOnline={message.author.is_online} />
            </div>
          )}
        </div>
      )}
      <div
        className={cn(
          'group relative flex max-w-[72%] flex-col gap-0.5 rounded-2xl px-3 py-1.5 text-sm leading-snug shadow-sm',
          isMine
            ? 'rounded-br-sm bg-primary text-primary-foreground'
            : 'rounded-bl-sm bg-muted text-foreground',
        )}
      >
        {!grouped && !isMine && (
          <span className="text-[11px] font-medium opacity-80">
            @{message.author.username}
          </span>
        )}
        {isDeleted ? (
          <span className="italic opacity-80">
            {message.placeholder ??
              (message.status === 'deleted_by_author'
                ? 'Сообщение удалено автором'
                : 'Скрыто модератором')}
          </span>
        ) : editing ? (
          <div className="flex flex-col gap-1.5">
            <textarea
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              rows={Math.min(5, Math.max(1, editDraft.split('\n').length))}
              className={cn(
                'resize-none rounded-md bg-background/80 px-2 py-1 text-sm text-foreground outline-none',
              )}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => editMutation.mutate()}
                disabled={editMutation.isPending}
              >
                Сохранить
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditing(false)
                  setEditDraft(docToText(message.content))
                }}
              >
                Отмена
              </Button>
            </div>
          </div>
        ) : (
          <span className="whitespace-pre-wrap break-words">
            {docToText(message.content)}
          </span>
        )}
        <span
          className={cn(
            'mt-0.5 self-end text-[10px] tabular-nums',
            isMine ? 'text-primary-foreground/70' : 'text-muted-foreground',
          )}
        >
          {time}
          {message.status === 'edited' ? ' · ред.' : ''}
        </span>
        {isMine && !isDeleted && !editing && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="absolute -left-7 top-1 h-6 w-6 opacity-0 group-hover:opacity-100"
                aria-label="Действия"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setEditing(true)}>
                Редактировать
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => deleteMutation.mutate()}
                className="text-destructive focus:text-destructive"
              >
                Удалить
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  )
}
