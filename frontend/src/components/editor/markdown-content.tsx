'use client'

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'

import { cn } from '@/lib/utils'

interface Props {
  markdown: string
  className?: string
}

/**
 * Render markdown content with KaTeX-rendered math and GFM extensions
 * (tables, strikethrough, task lists, autolinks).
 *
 * Used by the AI proposals panel: today the LLM pipeline returns a raw
 * markdown string wrapped in a single TipTap paragraph, so feeding that
 * into ProseMirror would just show the raw `#`/`**`/`$$…$$` characters.
 * This component renders proper headings, lists, code blocks, and
 * KaTeX-rendered formulas instead.
 *
 * We don't depend on `@tailwindcss/typography` (not installed), so block
 * styling is wired explicitly per element via the `components` prop.
 */
const components: Components = {
  h1: ({ children, ...rest }) => (
    <h1 className="mt-4 mb-2 text-2xl font-bold tracking-tight" {...rest}>
      {children}
    </h1>
  ),
  h2: ({ children, ...rest }) => (
    <h2 className="mt-4 mb-2 text-xl font-semibold tracking-tight" {...rest}>
      {children}
    </h2>
  ),
  h3: ({ children, ...rest }) => (
    <h3 className="mt-3 mb-1.5 text-lg font-semibold" {...rest}>
      {children}
    </h3>
  ),
  h4: ({ children, ...rest }) => (
    <h4 className="mt-3 mb-1 text-base font-semibold" {...rest}>
      {children}
    </h4>
  ),
  p: ({ children, ...rest }) => (
    <p className="my-2 leading-relaxed" {...rest}>
      {children}
    </p>
  ),
  ul: ({ children, ...rest }) => (
    <ul className="my-2 list-disc pl-6 [&>li]:my-1" {...rest}>
      {children}
    </ul>
  ),
  ol: ({ children, ...rest }) => (
    <ol className="my-2 list-decimal pl-6 [&>li]:my-1" {...rest}>
      {children}
    </ol>
  ),
  blockquote: ({ children, ...rest }) => (
    <blockquote
      className="my-3 border-l-4 border-primary/40 pl-3 italic text-muted-foreground"
      {...rest}
    >
      {children}
    </blockquote>
  ),
  hr: (props) => <hr className="my-4 border-border" {...props} />,
  a: ({ children, ...rest }) => (
    <a
      className="text-primary underline underline-offset-4"
      target="_blank"
      rel="noreferrer noopener"
      {...rest}
    >
      {children}
    </a>
  ),
  table: ({ children, ...rest }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...rest}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...rest }) => (
    <th
      className="border border-border bg-muted px-2 py-1 text-left font-semibold"
      {...rest}
    >
      {children}
    </th>
  ),
  td: ({ children, ...rest }) => (
    <td className="border border-border px-2 py-1 align-top" {...rest}>
      {children}
    </td>
  ),
  img: ({ alt, ...rest }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt ?? ''} className="my-2 max-w-full rounded-md" {...rest} />
  ),
  code: ({ className, children, ...rest }) => {
    const isInline = !className?.startsWith('language-')
    if (isInline) {
      return (
        <code
          className="rounded bg-muted px-1 py-0.5 text-[0.85em] font-mono"
          {...rest}
        >
          {children}
        </code>
      )
    }
    return (
      <code className={cn('font-mono text-sm', className)} {...rest}>
        {children}
      </code>
    )
  },
  pre: ({ children, ...rest }) => (
    <pre
      className="my-3 overflow-x-auto rounded-md bg-muted p-3 text-sm leading-relaxed"
      {...rest}
    >
      {children}
    </pre>
  ),
}

export function MarkdownContent({ markdown, className }: Props) {
  return (
    <div
      className={cn('text-sm', className)}
      data-testid="markdown-content"
    >
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}
