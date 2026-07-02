'use client'

import {
  Bookmark,
  Home,
  Key,
  LayoutGrid,
  Mail,
  Menu,
  User as UserIcon,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'

import { SearchBar } from '@/components/search/search-bar'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/lib/auth-store'
import { cn } from '@/lib/utils'

/**
 * Mobile-only burger menu. Slides in from the left, contains the same
 * navigation that desktop renders inline plus a search bar at the top.
 *
 * Closes when the pathname changes (so a tap on a link feels natural).
 */
export function MobileMenu({
  unreadDm,
}: {
  unreadDm: number
}) {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()
  const accessToken = useAuthStore((s) => s.accessToken)
  const isAuthed = Boolean(accessToken)

  // Close on route change.
  useEffect(() => {
    setOpen(false)
  }, [pathname])

  // Lock body scroll when open.
  useEffect(() => {
    if (typeof document === 'undefined') return
    if (open) {
      const prev = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = prev
      }
    }
  }, [open])

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        aria-label="Открыть меню"
        onClick={() => setOpen(true)}
        data-testid="mobile-menu-button"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Overlay + panel */}
      <div
        className={cn(
          'fixed inset-0 z-50 md:hidden',
          open ? 'pointer-events-auto' : 'pointer-events-none',
        )}
        aria-hidden={!open}
      >
        {/* backdrop */}
        <div
          className={cn(
            'absolute inset-0 bg-black/40 transition-opacity duration-200',
            open ? 'opacity-100' : 'opacity-0',
          )}
          onClick={() => setOpen(false)}
        />

        {/* panel */}
        <aside
          className={cn(
            'absolute left-0 top-0 flex h-full w-[85%] max-w-sm flex-col gap-4 border-r border-border p-4 shadow-2xl transition-transform duration-200',
            // Hard solid background — escape from any inherited transparency.
            'bg-white dark:bg-zinc-950',
            open ? 'translate-x-0' : '-translate-x-full',
          )}
          role="dialog"
          aria-modal="true"
          aria-label="Меню"
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold">Neuroforum</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Закрыть меню"
              onClick={() => setOpen(false)}
            >
              <X className="h-5 w-5" />
            </Button>
          </div>

          <SearchBar />

          <nav className="flex flex-col gap-1 text-sm">
            <MobileNavLink href="/" icon={<Home className="h-4 w-4" />}>
              Главная
            </MobileNavLink>
            <MobileNavLink
              href="/sections"
              icon={<LayoutGrid className="h-4 w-4" />}
            >
              Разделы
            </MobileNavLink>
            {isAuthed && (
              <>
                <MobileNavLink
                  href="/dm"
                  icon={<Mail className="h-4 w-4" />}
                  badge={unreadDm}
                >
                  Личные сообщения
                </MobileNavLink>
                <MobileNavLink
                  href="/me/saved"
                  icon={<Bookmark className="h-4 w-4" />}
                >
                  Сохранённое
                </MobileNavLink>
                <MobileNavLink
                  href="/me/credentials"
                  icon={<Key className="h-4 w-4" />}
                >
                  API-ключи
                </MobileNavLink>
                <MobileNavLink
                  href="/profile"
                  icon={<UserIcon className="h-4 w-4" />}
                >
                  Мой профиль
                </MobileNavLink>
              </>
            )}
            {!isAuthed && (
              <>
                <MobileNavLink
                  href="/login"
                  icon={<UserIcon className="h-4 w-4" />}
                >
                  Войти
                </MobileNavLink>
                <MobileNavLink
                  href="/register"
                  icon={<UserIcon className="h-4 w-4" />}
                >
                  Регистрация
                </MobileNavLink>
              </>
            )}
          </nav>
        </aside>
      </div>
    </>
  )
}

function MobileNavLink({
  href,
  icon,
  children,
  badge,
}: {
  href: string
  icon: React.ReactNode
  children: React.ReactNode
  badge?: number
}) {
  return (
    <Link
      href={href as never}
      className="flex items-center justify-between gap-3 rounded-md px-3 py-2.5 hover:bg-accent"
    >
      <span className="inline-flex items-center gap-2">
        {icon}
        {children}
      </span>
      {badge && badge > 0 ? (
        <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-destructive px-1.5 text-[10px] font-semibold text-destructive-foreground">
          {badge > 99 ? '99+' : badge}
        </span>
      ) : null}
    </Link>
  )
}
