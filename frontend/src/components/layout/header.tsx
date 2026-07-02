'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useTheme } from 'next-themes'
import {
  Bookmark,
  Key,
  Mail,
  Moon,
  Sun,
  User as UserIcon,
} from 'lucide-react'

import { MobileMenu } from '@/components/layout/mobile-menu'
import { NotificationsBell } from '@/components/notifications/notifications-bell'
import { SearchBar } from '@/components/search/search-bar'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import type { ConversationRead } from '@/lib/types'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { href: '/', label: 'Главная' },
] as const

export function Header() {
  const { theme, setTheme } = useTheme()
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const isAuthed = Boolean(accessToken)

  // Aggregate DM unread count from /conversations. Polled every 30s.
  const dmQuery = useQuery({
    queryKey: ['dm-unread-total'],
    queryFn: () => api.get('conversations').json<ConversationRead[]>(),
    enabled: isAuthed,
    refetchInterval: 30_000,
  })
  const dmUnread = (dmQuery.data ?? []).reduce(
    (acc, c) => acc + (c.unread_count || 0),
    0,
  )

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/80 backdrop-blur">
      <div className="container flex h-14 items-center justify-between gap-4">
        <div className="flex items-center gap-2 md:gap-6">
          <MobileMenu unreadDm={dmUnread} />
          <Link href="/" className="font-semibold tracking-tight">
            Neuroforum
          </Link>
          <nav className="hidden items-center gap-4 text-sm text-muted-foreground md:flex">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href as never}
                className={cn('transition-colors hover:text-foreground')}
              >
                {link.label}
              </Link>
            ))}
            <Link
              href="/sections"
              className="transition-colors hover:text-foreground"
            >
              Разделы
            </Link>
            {isAuthed && (
              <>
                <Link
                  href={'/dm' as never}
                  className="relative inline-flex items-center gap-1 transition-colors hover:text-foreground"
                  data-testid="header-dm-link"
                >
                  <Mail className="h-4 w-4" />
                  <span>ЛС</span>
                  {dmUnread > 0 && (
                    <span
                      className="ml-0.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground"
                      data-testid="header-dm-unread"
                    >
                      {dmUnread > 99 ? '99+' : dmUnread}
                    </span>
                  )}
                </Link>
                <Link
                  href={'/me/saved' as never}
                  className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                >
                  <Bookmark className="h-4 w-4" />
                  <span>Сохранённое</span>
                </Link>
                <Link
                  href={'/me/credentials' as never}
                  className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                >
                  <Key className="h-4 w-4" />
                  <span>Ключи</span>
                </Link>
              </>
            )}
          </nav>
        </div>

        <div className="hidden flex-1 justify-center md:flex">
          <SearchBar />
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Переключить тему"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          </Button>

          {isAuthed ? (
            <div className="flex items-center gap-2">
              <NotificationsBell />
              <Link
                href="/profile"
                className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent"
              >
                <UserIcon className="h-4 w-4" />
                <span data-testid="header-username">
                  {user?.username ?? 'Профиль'}
                </span>
              </Link>
              <Button variant="ghost" size="sm" onClick={() => clearAuth()}>
                Выйти
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost" size="sm">
                <Link href="/login">Войти</Link>
              </Button>
              <Button asChild size="sm">
                <Link href="/register">Регистрация</Link>
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
