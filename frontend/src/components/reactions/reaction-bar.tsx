'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import {
  REACTION_GLYPH,
  REACTION_KINDS,
  type ReactionKind,
} from '@/lib/types'
import { cn } from '@/lib/utils'

export interface ReactionBarProps {
  /** Either 'articles' or 'messages' — first path segment of the endpoint. */
  scope: 'articles' | 'messages'
  parentId: string
  counts: Partial<Record<ReactionKind, number>>
  /** queryKey of the parent to invalidate after toggle. */
  invalidateKey: readonly unknown[]
  /**
   * Optional override for "my reactions". When omitted (the common case) we
   * load/save the set in localStorage under a stable per-scope/per-parent key.
   * Backend currently doesn't echo back which kinds the caller used.
   */
  myReactions?: Set<ReactionKind>
}

function storageKey(scope: string, parentId: string) {
  return `my-reactions:${scope}:${parentId}`
}

function loadStored(scope: string, parentId: string): Set<ReactionKind> {
  if (typeof window === 'undefined') return new Set()
  try {
    const raw = window.localStorage.getItem(storageKey(scope, parentId))
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as unknown
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.filter((x): x is ReactionKind =>
      typeof x === 'string' && (REACTION_KINDS as readonly string[]).includes(x),
    ))
  } catch {
    return new Set()
  }
}

function persistStored(
  scope: string,
  parentId: string,
  set: Set<ReactionKind>,
) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      storageKey(scope, parentId),
      JSON.stringify([...set]),
    )
  } catch {
    /* ignore quota errors */
  }
}

export function ReactionBar({
  scope,
  parentId,
  counts,
  invalidateKey,
  myReactions: myReactionsProp,
}: ReactionBarProps) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const qc = useQueryClient()
  const [mine, setMine] = useState<Set<ReactionKind>>(() => new Set())
  const [pickerOpen, setPickerOpen] = useState(false)

  // Rehydrate from localStorage on mount (avoids SSR mismatch).
  useEffect(() => {
    if (myReactionsProp) {
      setMine(new Set(myReactionsProp))
      return
    }
    setMine(loadStored(scope, parentId))
  }, [scope, parentId, myReactionsProp])

  const mutation = useMutation({
    mutationFn: async (params: { kind: ReactionKind; remove: boolean }) => {
      if (params.remove) {
        await api.delete(`${scope}/${parentId}/reactions/${params.kind}`)
      } else {
        await api.post(`${scope}/${parentId}/reactions`, {
          json: { kind: params.kind },
        })
      }
      return params
    },
    onMutate: ({ kind, remove }) => {
      // Optimistic local tracking — backend doesn't return "my set".
      setMine((prev) => {
        const next = new Set(prev)
        if (remove) next.delete(kind)
        else next.add(kind)
        if (!myReactionsProp) persistStored(scope, parentId, next)
        return next
      })
    },
    onError: async (err, params) => {
      // Roll back optimistic flip.
      setMine((prev) => {
        const next = new Set(prev)
        if (params.remove) next.add(params.kind)
        else next.delete(params.kind)
        if (!myReactionsProp) persistStored(scope, parentId, next)
        return next
      })
      console.error(await extractErrorMessage(err, 'reaction toggle failed'))
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: invalidateKey })
    },
  })

  // Chips for reactions that actually have a count > 0 OR are in my own set
  // (so my own click stays visible while the server count catches up).
  const visibleKinds = useMemo<ReactionKind[]>(() => {
    const present: ReactionKind[] = []
    for (const k of REACTION_KINDS) {
      const c = counts[k] ?? 0
      if (c > 0 || mine.has(k)) present.push(k)
    }
    return present
  }, [counts, mine])

  function handleToggle(kind: ReactionKind) {
    if (!accessToken) return
    mutation.mutate({ kind, remove: mine.has(kind) })
  }

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label="Реакции"
    >
      {visibleKinds.map((k) => {
        const active = mine.has(k)
        // Effective count = server count, but bumped/decremented locally so
        // the UI doesn't visibly flicker between optimistic toggle and refetch.
        const serverCount = counts[k] ?? 0
        const count = serverCount
        return (
          <button
            key={k}
            type="button"
            onClick={() => handleToggle(k)}
            aria-label={k}
            aria-pressed={active}
            disabled={!accessToken || mutation.isPending}
            data-testid={`reaction-${k}`}
            title={accessToken ? k : 'Войдите, чтобы оставить реакцию'}
            className={cn(
              'inline-flex h-7 items-center gap-1 rounded-full border px-2 text-sm transition-colors',
              active
                ? 'border-primary bg-primary/15 font-semibold text-foreground'
                : 'border-border bg-background hover:bg-accent',
              !accessToken && 'cursor-default opacity-80',
            )}
          >
            <span aria-hidden>{REACTION_GLYPH[k]}</span>
            <span className="tabular-nums">{count}</span>
          </button>
        )
      })}
      {accessToken && (
        <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 rounded-full border border-dashed border-border"
              aria-label="Добавить реакцию"
              data-testid="reaction-picker-trigger"
              disabled={mutation.isPending}
              title="Добавить реакцию"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="flex flex-wrap gap-1 p-2"
            data-testid="reaction-picker"
          >
            {REACTION_KINDS.map((k) => {
              const active = mine.has(k)
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    handleToggle(k)
                    setPickerOpen(false)
                  }}
                  data-testid={`reaction-pick-${k}`}
                  className={cn(
                    'inline-flex h-9 w-9 items-center justify-center rounded-md border text-lg transition-colors',
                    active
                      ? 'border-primary bg-primary/15'
                      : 'border-transparent hover:bg-accent',
                  )}
                  aria-label={k}
                  title={k}
                >
                  <span aria-hidden>{REACTION_GLYPH[k]}</span>
                </button>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}
