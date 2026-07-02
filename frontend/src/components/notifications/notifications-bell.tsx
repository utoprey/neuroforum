'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import {
  formatRelative,
  renderNotification,
  type RenderedNotification,
} from '@/lib/notifications'
import { cn } from '@/lib/utils'
import type { NotificationRead } from '@/lib/types'

export function NotificationsBell() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const countQuery = useQuery({
    queryKey: ['notifications', 'count'],
    queryFn: () =>
      api.get('me/notifications/unread-count').json<{ count: number }>(),
    enabled: Boolean(accessToken),
    refetchInterval: 60_000,
  })

  const listQuery = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () =>
      api
        .get('me/notifications', { searchParams: { limit: 20 } })
        .json<NotificationRead[]>(),
    enabled: Boolean(accessToken) && open,
  })

  const markRead = useMutation({
    mutationFn: (ids: string[]) =>
      api
        .post('me/notifications/mark-read', { json: { ids } })
        .then(() => undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  if (!accessToken) return null

  const count = countQuery.data?.count ?? 0
  const items = listQuery.data ?? []
  const hasUnread = items.some((n) => !n.is_read)

  return (
    <div ref={rootRef} className="relative">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Уведомления"
        onClick={() => setOpen((v) => !v)}
        data-testid="notifications-bell"
      >
        <Bell className="h-4 w-4" />
        {count > 0 && (
          <span
            className={cn(
              'absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground',
            )}
          >
            {count > 99 ? '99+' : count}
          </span>
        )}
      </Button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-96 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-sm font-semibold">Уведомления</span>
            {hasUnread && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  const ids = items.filter((n) => !n.is_read).map((n) => n.id)
                  if (ids.length > 0) markRead.mutate(ids)
                }}
                disabled={markRead.isPending}
              >
                Прочитать всё
              </Button>
            )}
          </div>
          <div className="max-h-96 overflow-auto">
            {listQuery.isLoading && (
              <p className="px-3 py-2 text-sm text-muted-foreground">
                Загружаем…
              </p>
            )}
            {!listQuery.isLoading && items.length === 0 && (
              <p className="px-3 py-2 text-sm text-muted-foreground">
                Уведомлений нет.
              </p>
            )}
            <ul className="flex flex-col">
              {items.map((n) => {
                const r = renderNotification(n)
                return (
                  <NotificationItem
                    key={n.id}
                    notification={n}
                    rendered={r}
                    onClick={() => {
                      if (!n.is_read) markRead.mutate([n.id])
                      setOpen(false)
                    }}
                  />
                )
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

function NotificationItem({
  notification,
  rendered,
  onClick,
}: {
  notification: NotificationRead
  rendered: RenderedNotification
  onClick: () => void
}) {
  const { authorUsername, summary, snippet, href } = rendered
  const isUnread = !notification.is_read
  return (
    <li>
      <Link
        href={href as never}
        onClick={onClick}
        data-testid="notification-row"
        className={cn(
          'flex flex-col gap-0.5 rounded-sm px-3 py-2 text-sm transition-colors hover:bg-accent',
          isUnread && 'bg-accent/60',
        )}
      >
        <div className="flex items-baseline gap-1.5">
          {isUnread && (
            <span
              className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary"
              aria-hidden
            />
          )}
          <span
            className={cn(
              'leading-snug',
              isUnread ? 'text-foreground' : 'text-muted-foreground',
            )}
          >
            {authorUsername ? (
              <>
                <span className={cn(isUnread ? 'font-semibold' : 'font-medium')}>
                  @{authorUsername}
                </span>{' '}
              </>
            ) : null}
            {summary}
          </span>
        </div>
        {snippet && (
          <span className="line-clamp-2 pl-3.5 text-xs text-muted-foreground">
            «{snippet}»
          </span>
        )}
        <span className="pl-3.5 text-[11px] text-muted-foreground">
          {formatRelative(notification.created_at)}
        </span>
      </Link>
    </li>
  )
}
