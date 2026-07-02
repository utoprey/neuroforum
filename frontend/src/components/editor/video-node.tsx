'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type NodeViewProps,
} from '@tiptap/react'

import { resolveImageSrc } from '@/lib/upload'

/**
 * Custom TipTap node mirroring the backend `video` block:
 *
 *   { "type": "video", "attrs": { "attachment_id": "...", "src": "...", "caption": "..." } }
 *
 * Renders the `<video controls>` only when a `src` is present so we never
 * emit a broken player for legacy content that pre-dates the
 * `src`-on-content rollout (the backend enricher fills it in for new
 * fetches, but cached blobs may still arrive sans src).
 */
function VideoView({ node }: NodeViewProps) {
  const src = resolveImageSrc((node.attrs.src as string | null) ?? '')
  const caption = node.attrs.caption as string | undefined
  if (!src) {
    return (
      <NodeViewWrapper className="my-4 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        Видео недоступно
      </NodeViewWrapper>
    )
  }
  return (
    <NodeViewWrapper className="my-4">
      <video src={src} controls className="w-full rounded-md" />
      {caption && (
        <p className="mt-1 text-sm italic text-muted-foreground">{caption}</p>
      )}
    </NodeViewWrapper>
  )
}

export const VideoNode = Node.create({
  name: 'video',
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
      caption: { default: null },
    }
  },

  parseHTML() {
    return [{ tag: 'video[data-video]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'video',
      mergeAttributes(HTMLAttributes, {
        'data-video': '',
        controls: 'true',
        class: 'w-full rounded-md',
      }),
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(VideoView)
  },
})
