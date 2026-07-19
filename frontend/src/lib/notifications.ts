/**
 * Helpers for rendering NotificationRead rows in the bell dropdown.
 *
 * Backend wire-shape (see backend/app/modules/notifications/schemas.py):
 *
 *   { id, type: 'mention' | 'reply' | …, payload: {...}, is_read, created_at }
 *
 * Known payload shapes:
 *   mention/article_mention   → /articles/{article_id}
 *   mention/message_mention   → /articles/{article_id}#message-{message_id}
 *   reply/reply               → /articles/{article_id}#message-{message_id}
 *
 * Anything unknown gracefully degrades to a generic line + '#' href.
 */
import type { NotificationRead } from './types'

export interface RenderedNotification {
  /** Author handle for the `@username` prefix, if known. */
  authorUsername: string | null
  /** Human-readable summary, e.g. "упомянул(а) вас в статье «X»". */
  summary: string
  /** Optional secondary line (article/message snippet). */
  snippet: string | null
  /** Destination href. '#' means we couldn't extract a meaningful target. */
  href: string
}

function pickString(payload: Record<string, unknown>, key: string): string | null {
  const v = payload[key]
  return typeof v === 'string' && v.length > 0 ? v : null
}

export function renderNotification(n: NotificationRead): RenderedNotification {
  const p = (n.payload ?? {}) as Record<string, unknown>
  const kind = (pickString(p, 'kind') ?? '').toLowerCase()
  const author = pickString(p, 'author_username')
  const articleId = pickString(p, 'article_id')
  const articleTitle = pickString(p, 'article_title') ?? 'статья'
  const messageId = pickString(p, 'message_id')
  const snippetRaw = pickString(p, 'snippet')
  const snippet = snippetRaw
    ? snippetRaw.length > 160
      ? snippetRaw.slice(0, 157) + '…'
      : snippetRaw
    : null

  const articleHref = articleId ? `/articles/${articleId}` : '#'
  const messageHref =
    articleId && messageId
      ? `/articles/${articleId}#message-${messageId}`
      : articleHref

  if (n.type === 'mention') {
    if (kind === 'message_mention') {
      return {
        authorUsername: author,
        summary: `упомянул(а) вас в обсуждении «${articleTitle}»`,
        snippet,
        href: messageHref,
      }
    }
    return {
      authorUsername: author,
      summary: `упомянул(а) вас в статье «${articleTitle}»`,
      snippet,
      href: articleHref,
    }
  }

  if (n.type === 'reply') {
    return {
      authorUsername: author,
      summary: `ответил(а) вам в «${articleTitle}»`,
      snippet,
      href: messageHref,
    }
  }

  return {
    authorUsername: author,
    summary: `новое уведомление: ${n.type}`,
    snippet,
    href: articleHref,
  }
}

/**
 * Lightweight relative-time formatter (Russian). Avoids pulling in date-fns
 * for a single helper. Matches behaviour roughly: "только что", "5 мин назад",
 * "3 ч назад", "вчера", "12.06" (current year), "12.06.2023" (other years).
 */
export function formatRelative(input: string): string {
  const then = new Date(input)
  if (Number.isNaN(then.getTime())) return ''
  const now = Date.now()
  const diffSec = Math.round((now - then.getTime()) / 1000)

  if (diffSec < 30) return 'только что'
  if (diffSec < 60) return `${diffSec} сек назад`
  const min = Math.round(diffSec / 60)
  if (min < 60) return `${min} мин назад`
  const hours = Math.round(diffSec / 3600)
  if (hours < 24) return `${hours} ч назад`
  const days = Math.round(diffSec / 86400)
  if (days === 1) return 'вчера'
  if (days < 7) return `${days} дн назад`

  const sameYear = then.getFullYear() === new Date().getFullYear()
  return then.toLocaleDateString('ru', {
    day: '2-digit',
    month: '2-digit',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}
