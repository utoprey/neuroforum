'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'

import { SOCIAL_ICON_META } from '@/components/profile/social-icons'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { OnlineDot } from '@/components/user/online-dot'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import { SOCIAL_KEYS } from '@/lib/schemas/auth'
import type {
  RecentMessage,
  RecentTopic,
  SavedArticleRead,
  UserRead,
} from '@/lib/types'

export interface ProfileViewProps {
  /** Full user object — must include `profile` + `stats` for full rendering. */
  user: UserRead
  /** When true, also show the user's "Saved" list (only meaningful for self). */
  showSaved?: boolean
  /** Whether the viewer is looking at their own profile. Defaults to `showSaved`. */
  isOwnProfile?: boolean
  /** Right-aligned actions slot — e.g. "Редактировать профиль" button. */
  actions?: React.ReactNode
}

export function ProfileView({
  user,
  showSaved = false,
  isOwnProfile,
  actions,
}: ProfileViewProps) {
  const ownProfile = isOwnProfile ?? showSaved
  const profile = user.profile
  const stats = user.stats

  const recentTopicsQuery = useQuery({
    queryKey: ['users', user.username, 'recent-topics'],
    queryFn: () =>
      api
        .get(`users/${user.username}/recent-topics`, {
          searchParams: { limit: 10 },
        })
        .json<RecentTopic[]>(),
  })

  const recentMessagesQuery = useQuery({
    queryKey: ['users', user.username, 'recent-messages'],
    queryFn: () =>
      api
        .get(`users/${user.username}/recent-messages`, {
          searchParams: { limit: 10 },
        })
        .json<RecentMessage[]>(),
  })

  const savedQuery = useQuery({
    queryKey: ['users', user.username, 'saved'],
    queryFn: () =>
      api
        .get('me/saved', { searchParams: { limit: 5 } })
        .json<SavedArticleRead[]>(),
    enabled: showSaved,
  })

  const socialEntries = SOCIAL_KEYS.map((key) => {
    const v = profile?.social_links?.[key]
    return typeof v === 'string' && v ? ([key, v] as const) : null
  }).filter((x): x is readonly [(typeof SOCIAL_KEYS)[number], string] => x !== null)

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-row items-start gap-4 space-y-0">
          <div className="relative">
            <Avatar className="h-20 w-20 text-2xl">
              {profile?.avatar_url ? (
                <AvatarImage src={profile.avatar_url} alt={user.username} />
              ) : null}
              <AvatarFallback>
                {(profile?.display_name?.[0] ?? user.username[0]).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <OnlineDot
              isOnline={user.is_online}
              className="h-3.5 w-3.5"
            />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <CardTitle className="text-2xl">
              {profile?.display_name || user.username}
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2">
              <span>@{user.username}</span>
              <Badge variant="secondary">{user.role}</Badge>
              {profile?.orcid && (
                <a
                  href={`https://orcid.org/${profile.orcid}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-full border border-green-700 bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-900 hover:bg-green-200 dark:bg-green-950 dark:text-green-200"
                >
                  ORCID {profile.orcid}
                </a>
              )}
            </CardDescription>
            {profile?.bio && (
              <p className="mt-2 whitespace-pre-line text-sm text-foreground">
                {profile.bio}
              </p>
            )}
            {socialEntries.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {socialEntries.map(([key, href]) => {
                  const meta = SOCIAL_ICON_META[key]
                  const Icon = meta.Icon
                  return (
                    <a
                      key={key}
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      title={meta.label}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span>{meta.label}</span>
                    </a>
                  )
                })}
              </div>
            )}
          </div>
          {actions ? <div className="shrink-0">{actions}</div> : null}
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 border-t pt-4 text-sm sm:grid-cols-4">
          <Stat
            label="Статьи"
            value={stats?.articles_count ?? 0}
            href={`/users/${user.username}/articles`}
          />
          <Stat
            label="Сообщения"
            value={stats?.messages_count ?? 0}
            href={`/users/${user.username}/messages`}
          />
          <Stat
            label="Реакции"
            value={stats?.received_reactions_count ?? 0}
            href={`/users/${user.username}/reactions`}
          />
          <Stat
            label="Сохранённые"
            value={stats?.saved_articles_count ?? 0}
            href={ownProfile ? '/me/saved' : undefined}
            disabledTooltip={ownProfile ? undefined : 'приватно'}
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Последние темы</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {recentTopicsQuery.isLoading && (
              <span className="text-muted-foreground">Загрузка…</span>
            )}
            {recentTopicsQuery.data && recentTopicsQuery.data.length === 0 && (
              <span className="text-muted-foreground">Пока пусто.</span>
            )}
            {recentTopicsQuery.data?.map((t) => (
              <Link
                key={t.id}
                href={`/topics/${t.id}/articles` as never}
                className="flex items-baseline justify-between gap-2 rounded-md px-2 py-1 hover:bg-accent"
              >
                <span className="line-clamp-1">{t.title}</span>
                {t.last_message_at && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {new Date(t.last_message_at).toLocaleDateString('ru')}
                  </span>
                )}
              </Link>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Последние сообщения</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {recentMessagesQuery.isLoading && (
              <span className="text-muted-foreground">Загрузка…</span>
            )}
            {recentMessagesQuery.data &&
              recentMessagesQuery.data.length === 0 && (
                <span className="text-muted-foreground">Пока пусто.</span>
              )}
            {recentMessagesQuery.data?.map((m) => (
              <Link
                key={m.id}
                href={`/articles/${m.article_id}` as never}
                className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 hover:bg-accent"
              >
                <span className="line-clamp-1 font-medium">
                  {m.article_title}
                </span>
                <span className="line-clamp-2 text-xs text-muted-foreground">
                  {m.snippet}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {new Date(m.created_at).toLocaleString('ru')}
                </span>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      {showSaved && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Сохранённое</CardTitle>
            <CardDescription>
              <Link
                href={'/me/saved' as never}
                className="text-primary hover:underline"
              >
                Все сохранённые →
              </Link>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {savedQuery.isLoading && (
              <span className="text-muted-foreground">Загрузка…</span>
            )}
            {savedQuery.data && savedQuery.data.length === 0 && (
              <span className="text-muted-foreground">Пока пусто.</span>
            )}
            {savedQuery.data?.map((s) => (
              <Link
                key={s.article_id}
                href={`/articles/${s.article.id}` as never}
                className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 hover:bg-accent"
              >
                <span className="line-clamp-1 font-medium">
                  {s.article.title}
                </span>
                {s.article.summary && (
                  <span className="line-clamp-2 text-xs text-muted-foreground">
                    {s.article.summary}
                  </span>
                )}
              </Link>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  href,
  disabledTooltip,
}: {
  label: string
  value: number
  href?: string
  disabledTooltip?: string
}) {
  const inner = (
    <>
      <span className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-xl font-semibold">{value}</span>
    </>
  )
  if (href) {
    return (
      <Link
        href={href as never}
        className="flex flex-col rounded-md border border-transparent p-2 transition-colors hover:cursor-pointer hover:border-primary/50 hover:bg-accent"
      >
        {inner}
      </Link>
    )
  }
  return (
    <div
      className="flex flex-col rounded-md border border-transparent p-2 opacity-60"
      title={disabledTooltip}
    >
      {inner}
    </div>
  )
}
