'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { UnifiedSearchResult } from '@/lib/types'
import { articleHref } from '@/lib/url-utils'

/**
 * Debounced search dropdown. Calls `GET /search?q=&type=all&limit=10`.
 * If the query starts with `@` we pass it through unchanged — the backend's
 * user-search endpoint already understands the prefix syntax.
 */
export function SearchBar() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  // Debounce
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(q.trim()), 200)
    return () => window.clearTimeout(handle)
  }, [q])

  // Close on outside click
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const query = useQuery({
    queryKey: ['search', debounced],
    queryFn: () =>
      api
        .get('search', {
          searchParams: { q: debounced, type: 'all', limit: 10 },
        })
        .json<UnifiedSearchResult>(),
    enabled: debounced.length >= 2,
    staleTime: 30_000,
  })

  const hasResults =
    query.data &&
    (query.data.articles.length > 0 ||
      query.data.messages.length > 0 ||
      query.data.users.length > 0)

  return (
    <div ref={rootRef} className="relative w-full max-w-md">
      <Input
        type="search"
        placeholder="Поиск (@user, статья…)"
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        aria-label="Поиск"
        data-testid="header-search-input"
      />
      {open && debounced.length >= 2 && (
        <div
          className={cn(
            'absolute left-0 right-0 top-full z-50 mt-1 max-h-96 overflow-auto rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-md',
          )}
        >
          {query.isLoading && (
            <p className="px-2 py-1 text-sm text-muted-foreground">Ищем…</p>
          )}
          {query.isError && (
            <p className="px-2 py-1 text-sm text-destructive">
              Поиск не выполнен.
            </p>
          )}
          {!query.isLoading && !hasResults && (
            <p className="px-2 py-1 text-sm text-muted-foreground">
              Ничего не найдено.
            </p>
          )}
          {query.data?.users.length ? (
            <Section title="Пользователи">
              {query.data.users.map((u) => (
                <ResultRow
                  key={u.id}
                  href={`/users/${u.username}` as never}
                  onSelect={() => setOpen(false)}
                  primary={`@${u.username}`}
                  secondary={u.display_name ?? undefined}
                />
              ))}
            </Section>
          ) : null}
          {query.data?.articles.length ? (
            <Section title="Статьи">
              {query.data.articles.map((hit) => (
                <ResultRow
                  key={hit.article.id}
                  href={articleHref(hit.article) as never}
                  onSelect={() => setOpen(false)}
                  primary={hit.article.title}
                  secondary={hit.snippet || hit.article.summary || undefined}
                />
              ))}
            </Section>
          ) : null}
          {query.data?.messages.length ? (
            <Section title="Сообщения">
              {query.data.messages.map((hit) => (
                <ResultRow
                  key={hit.message_id}
                  href={`/articles/${hit.article_id}` as never}
                  onSelect={() => setOpen(false)}
                  primary={hit.snippet || 'комментарий'}
                  secondary={undefined}
                />
              ))}
            </Section>
          ) : null}
        </div>
      )}
    </div>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="py-1">
      <div className="px-2 pb-1 text-xs uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <ul>{children}</ul>
    </div>
  )
}

function ResultRow({
  href,
  primary,
  secondary,
  onSelect,
}: {
  href: string
  primary: string
  secondary?: string
  onSelect: () => void
}) {
  return (
    <li>
      <Link
        href={href as never}
        onClick={onSelect}
        className="block rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
      >
        <div className="line-clamp-1 font-medium">{primary}</div>
        {secondary && (
          <div className="line-clamp-1 text-xs text-muted-foreground">
            {secondary}
          </div>
        )}
      </Link>
    </li>
  )
}
