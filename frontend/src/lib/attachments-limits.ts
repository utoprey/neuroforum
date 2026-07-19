'use client'

import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type {
  AttachmentKind,
  AttachmentKindLimits,
  AttachmentLimits,
} from './types'

export type AttachmentLimitsMap = Map<AttachmentKind, AttachmentKindLimits>

/**
 * Fetch and cache the `GET /attachments/limits` payload. The result is a
 * `Map<kind, limits>` so callers can quickly look up the max size and the
 * accepted MIME types for a given upload kind.
 *
 * Falls back to a sane local default while the request is in flight or fails,
 * so the editor remains usable even without an authenticated session.
 */
export function useAttachmentLimits(): {
  limits: AttachmentLimitsMap
  isLoading: boolean
} {
  const query = useQuery({
    queryKey: ['attachments-limits'],
    queryFn: () => api.get('attachments/limits').json<AttachmentLimits>(),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 0,
  })

  const limits: AttachmentLimitsMap = new Map()
  if (query.data) {
    for (const item of query.data.kinds) {
      limits.set(item.kind, item)
    }
  } else {
    // Reasonable defaults, used only as a UI hint when the API call fails.
    limits.set('image', {
      kind: 'image',
      max_bytes: 20 * 1024 * 1024,
      max_mb: 20,
      allowed_mime_types: ['image/jpeg', 'image/png', 'image/webp'],
    })
    limits.set('gif', {
      kind: 'gif',
      max_bytes: 20 * 1024 * 1024,
      max_mb: 20,
      allowed_mime_types: ['image/gif'],
    })
    limits.set('video', {
      kind: 'video',
      max_bytes: 200 * 1024 * 1024,
      max_mb: 200,
      allowed_mime_types: ['video/mp4', 'video/webm'],
    })
    limits.set('file', {
      kind: 'file',
      max_bytes: 50 * 1024 * 1024,
      max_mb: 50,
      allowed_mime_types: [],
    })
  }

  return { limits, isLoading: query.isLoading }
}

export function guessKind(mimeType: string): AttachmentKind {
  if (mimeType === 'image/gif') return 'gif'
  if (mimeType.startsWith('image/')) return 'image'
  if (mimeType.startsWith('video/')) return 'video'
  return 'file'
}

export function humanizeBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}
