import type { JSONContent } from '@tiptap/react'

/**
 * Extracts a plain markdown string from a backend `proposed_content` blob.
 *
 * Today our LLM pipeline wraps its raw markdown response into a single
 * `doc → paragraph → text` node — that's the only shape this helper
 * recognises. If the content is an actual structured ProseMirror document
 * (multiple block types, marks, custom nodes, etc.), we return `null` so
 * callers can fall back to the regular TipTap renderer.
 *
 * The detection is intentionally narrow: any mark on the text, any non-text
 * child, or more than one block at the document root → treated as a real
 * doc and we return `null`.
 */
export function extractMarkdownFromDoc(
  content: JSONContent | undefined | null,
): string | null {
  if (!content || content.type !== 'doc' || !Array.isArray(content.content)) {
    return null
  }
  if (content.content.length === 0) return null

  // Accept either: (a) single paragraph wrapping the raw markdown blob, or
  // (b) several paragraph nodes — Pydantic/ProseMirror normalisation splits
  // a multi-line LLM response into N paragraphs at `\n\n` boundaries, but
  // the inner text nodes still hold the original markdown syntax.
  const paragraphs: string[] = []
  for (const node of content.content) {
    if (!node || node.type !== 'paragraph' || !Array.isArray(node.content)) {
      return null
    }
    const allUnmarkedText = node.content.every(
      (c) => c && c.type === 'text' && !c.marks?.length,
    )
    if (!allUnmarkedText) return null
    const paraText = node.content
      .map((c) => (c as { text?: string }).text ?? '')
      .join('')
    paragraphs.push(paraText)
  }

  const joined = paragraphs.join('\n\n')

  // Heuristic: only treat as markdown if it actually contains some markdown
  // syntax. Otherwise a single plain-text paragraph (e.g. an edited
  // proposal that's just one sentence) would lose its plain look.
  if (!looksLikeMarkdown(joined)) return null

  return joined
}

/**
 * Build a minimal ProseMirror doc that wraps a markdown blob into a single
 * paragraph. The backend's Pydantic / ProseMirror normalisation may later
 * split it on `\n\n` into multiple paragraphs — that's fine, the renderer
 * + extractor both handle either shape.
 *
 * Empty markdown produces an empty paragraph (no children) so we don't
 * emit an invalid `{type: 'text', text: ''}` node — TipTap rejects those.
 */
export function markdownToDoc(markdown: string): JSONContent {
  return {
    type: 'doc',
    content: [
      {
        type: 'paragraph',
        content: markdown ? [{ type: 'text', text: markdown }] : [],
      },
    ],
  }
}

function looksLikeMarkdown(text: string): boolean {
  // Cheap markers: headings, bold, italic, code fences, list markers,
  // block math, horizontal rules, inline math, links.
  return (
    /(^|\n)#{1,6}\s/.test(text) ||
    /\*\*[^*]+\*\*/.test(text) ||
    /(^|\s)\*[^*\s][^*]*\*(\s|$)/.test(text) ||
    /```/.test(text) ||
    /(^|\n)[-*+]\s/.test(text) ||
    /(^|\n)\d+\.\s/.test(text) ||
    /(^|\n)>\s/.test(text) ||
    /(^|\n)---+\s*(\n|$)/.test(text) ||
    /\$\$[\s\S]+?\$\$/.test(text) ||
    /\$[^$\n]+\$/.test(text) ||
    /\[[^\]]+\]\([^)]+\)/.test(text)
  )
}
