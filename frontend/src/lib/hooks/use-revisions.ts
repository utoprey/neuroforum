'use client'

import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ArticleRevisionRead } from '@/lib/types'

/**
 * Lists all revisions for an article (auth required). Used by the revisions
 * page and by the article view header (revision counter).
 */
export function useArticleRevisions(articleId: string, enabled = true) {
  return useQuery({
    queryKey: ['article', articleId, 'revisions'],
    queryFn: () =>
      api.get(`articles/${articleId}/revisions`).json<ArticleRevisionRead[]>(),
    enabled,
  })
}
