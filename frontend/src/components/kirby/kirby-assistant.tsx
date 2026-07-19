'use client'

import { X } from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { KirbySvg } from './kirby-svg'
import { tipsForRoute, type KirbyTip } from './kirby-tips'

const SNOOZE_KEY = 'neuroforum-kirby-snooze'
const SNOOZE_MS = 24 * 60 * 60 * 1000

function pickRandom<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)]
}

export function KirbyAssistant() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [snoozed, setSnoozed] = useState(false)
  const [tip, setTip] = useState<KirbyTip | null>(null)

  useEffect(() => {
    const raw = window.localStorage.getItem(SNOOZE_KEY)
    if (!raw) return
    const until = Number(raw)
    if (Number.isFinite(until) && until > Date.now()) {
      setSnoozed(true)
    } else {
      window.localStorage.removeItem(SNOOZE_KEY)
    }
  }, [])

  const tips = useMemo(() => tipsForRoute(pathname ?? '/'), [pathname])

  useEffect(() => {
    if (open) {
      setTip(pickRandom(tips))
    }
  }, [open, tips])

  if (snoozed) return null

  const shuffle = () => setTip(pickRandom(tips))

  const snooze = () => {
    window.localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS))
    setSnoozed(true)
    setOpen(false)
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex flex-col items-end gap-2 sm:bottom-6 sm:right-6">
      {open && tip ? (
        <div
          role="dialog"
          aria-label="Подсказка Кирби"
          className="pointer-events-auto w-72 max-w-[80vw] rounded-2xl border border-border bg-background p-4 shadow-lg animate-in fade-in slide-in-from-bottom-2"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm leading-snug text-foreground">{tip.text}</p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-full p-1 text-muted-foreground transition hover:bg-muted"
              aria-label="Закрыть"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {tip.href ? (
            <a
              href={tip.href}
              onClick={() => setOpen(false)}
              className="mt-3 inline-flex text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              {tip.hrefLabel ?? 'Перейти'} →
            </a>
          ) : null}
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <button
              type="button"
              onClick={shuffle}
              className="rounded-md px-2 py-1 transition hover:bg-muted"
            >
              ещё совет
            </button>
            <button
              type="button"
              onClick={snooze}
              className="rounded-md px-2 py-1 transition hover:bg-muted"
            >
              не показывать сегодня
            </button>
          </div>
        </div>
      ) : null}

      <Button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="kirby-button"
        variant="ghost"
        aria-label={open ? 'Закрыть подсказку' : 'Показать подсказку Кирби'}
        className={cn(
          'pointer-events-auto h-14 w-14 rounded-full border border-border bg-background p-1 shadow-md transition hover:scale-105 hover:bg-background',
          !open && 'animate-kirby-bounce',
        )}
      >
        <KirbySvg className="h-full w-full" />
      </Button>
    </div>
  )
}
