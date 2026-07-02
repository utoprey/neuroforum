'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  NodeViewContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type NodeViewProps,
} from '@tiptap/react'

/**
 * Custom TipTap block node mirroring the backend `quote` block:
 *
 *   { "type": "quote", "attrs": { "cite_url": "..." }, "content": [paragraph, ...] }
 *
 * Distinct from StarterKit's `blockquote` (which has no `cite_url`).
 * Without this node, TipTap's strict ProseMirror schema rejects any
 * document containing a `quote` block — silently wiping the whole
 * article body during `setContent`.
 */
function QuoteView({ node }: NodeViewProps) {
  const citeUrl = (node.attrs.cite_url as string | null) ?? null
  return (
    <NodeViewWrapper className="my-4 border-l-4 border-primary/40 bg-muted/40 pl-4 pr-2 py-2 rounded-r">
      <NodeViewContent className="italic text-muted-foreground" />
      {citeUrl ? (
        <a
          href={citeUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1 inline-block text-xs text-primary hover:underline"
        >
          источник →
        </a>
      ) : null}
    </NodeViewWrapper>
  )
}

export const QuoteNode = Node.create({
  name: 'quote',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return {
      cite_url: {
        default: null,
        parseHTML: (el) => el.getAttribute('data-cite-url'),
        renderHTML: (attrs) => {
          if (!attrs.cite_url) return {}
          return { 'data-cite-url': attrs.cite_url as string }
        },
      },
    }
  },

  parseHTML() {
    return [{ tag: 'blockquote[data-cite-quote]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['blockquote', mergeAttributes(HTMLAttributes, { 'data-cite-quote': '' }), 0]
  },

  addNodeView() {
    return ReactNodeViewRenderer(QuoteView)
  },
})
