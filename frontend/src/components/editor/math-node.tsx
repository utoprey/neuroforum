'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type NodeViewProps,
} from '@tiptap/react'
import { InlineMath, BlockMath } from 'react-katex'

/**
 * Custom TipTap node for KaTeX-rendered math. JSON shape matches what we
 * store in the article JSONB (see `docs/data-model.md` -> "math" block):
 *
 *   { "type": "math", "attrs": { "latex": "...", "display": true|false } }
 *
 * Both inline and block math live in the same node, distinguished by
 * `attrs.display`. They serialize/deserialize 1:1 with the backend schema.
 */
export const MathNode = Node.create({
  name: 'math',

  group: 'block',

  atom: true,

  selectable: true,

  draggable: false,

  addAttributes() {
    return {
      latex: {
        default: '',
      },
      display: {
        default: true,
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-math]',
        getAttrs: (node: HTMLElement | string) => {
          if (typeof node === 'string') return false
          return {
            latex: node.getAttribute('data-latex') ?? '',
            display: node.getAttribute('data-display') !== 'false',
          }
        },
      },
    ]
  },

  renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-math': '',
        'data-latex': String(HTMLAttributes.latex ?? ''),
        'data-display': String(HTMLAttributes.display),
      }),
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(MathNodeView)
  },
})

function MathNodeView(props: NodeViewProps) {
  const latex = (props.node.attrs.latex as string) || ''
  const display = (props.node.attrs.display as boolean) ?? true
  const editable = props.editor.isEditable
  return (
    <NodeViewWrapper
      as={display ? 'div' : 'span'}
      data-math
      data-display={String(display)}
      className={display ? 'my-2 rounded border border-border p-2' : 'inline-block'}
    >
      {latex ? (
        display ? (
          <BlockMath math={latex} />
        ) : (
          <InlineMath math={latex} />
        )
      ) : (
        <span className="italic text-muted-foreground">пустая формула</span>
      )}
      {editable && (
        <button
          type="button"
          className="ml-2 text-xs text-muted-foreground hover:underline"
          onClick={() => {
            const next = window.prompt('LaTeX', latex)
            if (next === null) return
            props.updateAttributes({ latex: next })
          }}
        >
          ред.
        </button>
      )}
    </NodeViewWrapper>
  )
}
