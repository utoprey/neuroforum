'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  ReactNodeViewRenderer,
  NodeViewWrapper,
  NodeViewContent,
  type NodeViewProps,
} from '@tiptap/react'
import { AlertTriangle, Info, StickyNote } from 'lucide-react'

/**
 * Block-level `callout` node. Seed-data emits e.g.
 *
 *   {
 *     "type": "callout",
 *     "attrs": { "kind": "info" | "warn" | "note", "icon": null },
 *     "content": [ { "type": "paragraph", ... } ]
 *   }
 *
 * Renders with a colored left border + icon and embeds the nested block
 * content via TipTap's NodeViewContent so paragraphs/headings inside keep
 * working with the standard editor commands.
 */
const KIND_ICON = {
  info: Info,
  warn: AlertTriangle,
  note: StickyNote,
} as const

const KIND_CLASSES = {
  info: 'border-blue-500 bg-blue-500/10 text-blue-600 dark:text-blue-300',
  warn: 'border-amber-500 bg-amber-500/10 text-amber-600 dark:text-amber-300',
  note: 'border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
} as const

type CalloutKind = keyof typeof KIND_ICON

function CalloutView({ node }: NodeViewProps) {
  const raw = (node.attrs.kind as string | null) ?? 'info'
  const kind: CalloutKind = raw in KIND_ICON ? (raw as CalloutKind) : 'info'
  const Icon = KIND_ICON[kind]
  const cls = KIND_CLASSES[kind]
  return (
    <NodeViewWrapper
      data-callout
      data-kind={kind}
      className={`my-3 flex gap-3 rounded-md border-l-4 p-4 ${cls}`}
    >
      <Icon className="mt-1 h-5 w-5 shrink-0" aria-hidden />
      <NodeViewContent className="prose prose-sm dark:prose-invert max-w-none flex-1 text-foreground [&_p]:my-0" />
    </NodeViewWrapper>
  )
}

export const CalloutNode = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return {
      kind: { default: 'info' },
      icon: { default: null },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-callout]',
        getAttrs: (el) => {
          if (typeof el === 'string') return false
          return {
            kind: el.getAttribute('data-kind') ?? 'info',
            icon: el.getAttribute('data-icon'),
          }
        },
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes({
        'data-callout': '',
        'data-kind': (HTMLAttributes.kind as string) ?? 'info',
      }),
      0,
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(CalloutView)
  },
})
