'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  ReactNodeViewRenderer,
  NodeViewWrapper,
  type NodeViewProps,
} from '@tiptap/react'
import Link from 'next/link'

/**
 * Inline `mention` node. Seed-data and backend may emit either
 *
 *   { "type": "mention", "attrs": { "user_id": "<uuid>", "username": "…" } }
 *
 * — `username` is preferred for routing/display; `user_id` is the canonical
 * reference. If neither is enriched, we fall back to a short UUID slice so
 * we never render an empty pill.
 */
function MentionView({ node }: NodeViewProps) {
  const userId = (node.attrs.user_id as string | null) ?? ''
  const username = (node.attrs.username as string | null) ?? null
  const explicitLabel = (node.attrs.label as string | null) ?? null

  const fallbackLabel = username
    ? `@${username}`
    : userId
      ? `@${userId.slice(0, 8)}`
      : '@user'
  const label = explicitLabel || fallbackLabel
  const href = username ? `/users/${username}` : '#'

  return (
    <NodeViewWrapper as="span" className="inline-block">
      <Link
        href={href as never}
        className="font-medium text-primary hover:underline"
        data-testid="mention-link"
      >
        {label}
      </Link>
    </NodeViewWrapper>
  )
}

export const MentionNode = Node.create({
  name: 'mention',
  inline: true,
  group: 'inline',
  selectable: false,
  atom: true,

  addAttributes() {
    return {
      user_id: { default: null },
      username: { default: null },
      label: { default: null },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-mention]',
        getAttrs: (el) => {
          if (typeof el === 'string') return false
          return {
            user_id: el.getAttribute('data-user-id'),
            username: el.getAttribute('data-username'),
            label: el.textContent,
          }
        },
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    const username = HTMLAttributes.username as string | undefined
    const userId = HTMLAttributes.user_id as string | undefined
    const label =
      (HTMLAttributes.label as string | undefined) ||
      (username ? `@${username}` : userId ? `@${userId.slice(0, 8)}` : '@user')
    return [
      'span',
      mergeAttributes({
        'data-mention': '',
        'data-user-id': userId ?? '',
        'data-username': username ?? '',
        class: 'font-medium text-primary',
      }),
      label,
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(MentionView)
  },
})
