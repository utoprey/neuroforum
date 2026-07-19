/**
 * URL helpers for slug-based forum routes.
 *
 * Hybrid Хабр-style URL scheme:
 *   /sections/<section_slug>/topics/<topic_slug>
 *   /sections/<section_slug>/topics/<topic_slug>/articles
 *   /articles/<uuid>-<slug>     ← UUID каноничен, slug косметика
 *
 * Article URLs always carry the UUID prefix so the canonical id never
 * breaks even if the slug is renamed or absent. The helpers below let
 * components build / parse those URLs in a single line.
 */

const UUID_RE = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-(.*))?$/i

export interface ParsedArticleParam {
  /** Canonical 36-char UUID extracted from the URL segment. */
  uuid: string
  /** The slug suffix (without leading dash), or ``null`` when absent. */
  slug: string | null
}

/**
 * Parse a Next.js route segment that may carry either a bare UUID or
 * ``<uuid>-<slug>``. When the input doesn't match the UUID prefix we
 * return it as-is in ``uuid`` (defensive: the API call will 404 cleanly
 * rather than silently truncating to a partial id).
 */
export function parseArticleSlugParam(param: string): ParsedArticleParam {
  const m = param.match(UUID_RE)
  if (!m) return { uuid: param, slug: null }
  return { uuid: m[1], slug: m[2] ?? null }
}

/**
 * Build the canonical href for an article. Includes the slug suffix when
 * available so the URL is human-readable; falls back to bare UUID when
 * the article has no slug yet.
 */
export function articleHref(article: {
  id: string
  slug?: string | null
}): string {
  return article.slug ? `/articles/${article.id}-${article.slug}` : `/articles/${article.id}`
}

/** Build the slug-based href for a topic's article list. */
export function topicArticlesHref(topic: {
  section_slug: string
  slug: string
}): string {
  return `/sections/${topic.section_slug}/topics/${topic.slug}/articles`
}

/** Build the slug-based href for a topic's "new article" form. */
export function topicNewArticleHref(topic: {
  section_slug: string
  slug: string
}): string {
  return `/sections/${topic.section_slug}/topics/${topic.slug}/articles/new`
}
