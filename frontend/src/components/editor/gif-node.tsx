'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type NodeViewProps,
} from '@tiptap/react'

import { resolveImageSrc } from '@/lib/upload'

/**
 * Custom TipTap node mirroring the backend `gif` block:
 *
 *   { "type": "gif", "attrs": { "attachment_id": "...", "src": "...", "alt": "..." } }
 *
 * Rendered as a plain `<img>` — browsers handle animated GIFs
 * (and animated WebPs) natively in `<img>` tags. A separate node
 * (rather than reusing `image`) keeps the backend schema explicit
 * about content kind so reactions/filters can target gifs vs images.
 */
function GifView({ node }: NodeViewProps) {
  const src = resolveImageSrc((node.attrs.src as string | null) ?? '')
  const alt = (node.attrs.alt as string | null) ?? ''
  if (!src) {
    return (
      <NodeViewWrapper className="my-3 rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
        GIF недоступен
      </NodeViewWrapper>
    )
  }
  return (
    <NodeViewWrapper className="my-3">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="max-w-full rounded-md" />
    </NodeViewWrapper>
  )
}

export const GifNode = Node.create({
  name: 'gif',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      attachment_id: {
        default: null,
        parseHTML: (el) => el.getAttribute('data-attachment-id'),
        renderHTML: (attrs) => {
          if (!attrs.attachment_id) return {}
          return { 'data-attachment-id': attrs.attachment_id as string }
        },
      },
      src: {
        default: null,
        parseHTML: (el) => el.getAttribute('src'),
        renderHTML: (attrs) => {
          const src = attrs.src as string | undefined
          return src ? { src: resolveImageSrc(src) } : {}
        },
      },
      alt: { default: null },
    }
  },

  parseHTML() {
    return [{ tag: 'img[data-gif]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'img',
      mergeAttributes(HTMLAttributes, {
        'data-gif': '',
        class: 'my-3 rounded-md max-w-full',
      }),
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(GifView)
  },
})
