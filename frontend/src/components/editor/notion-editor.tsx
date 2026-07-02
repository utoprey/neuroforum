'use client'

import { useEditor, EditorContent, type JSONContent, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import Underline from '@tiptap/extension-underline'
import Highlight from '@tiptap/extension-highlight'
import { Color } from '@tiptap/extension-color'
import TextStyle from '@tiptap/extension-text-style'
import { common, createLowlight } from 'lowlight'
import { Markdown } from 'tiptap-markdown'
import {
  Bold,
  Italic,
  Underline as UnderlineIcon,
  Strikethrough,
  Highlighter,
  Palette,
  Heading1,
  Heading2,
  Heading3,
  Pilcrow,
  ChevronDown,
  Code,
  Link as LinkIcon,
  Image as ImageIcon,
  Sigma,
  List as ListIcon,
  ListOrdered,
  Quote,
  Loader2,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAttachmentLimits } from '@/lib/attachments-limits'
import { uploadAttachment, UploadValidationError, resolveImageSrc } from '@/lib/upload'
import { cn } from '@/lib/utils'

import { CalloutNode } from './callout-node'
import { GifNode } from './gif-node'
import { LatexDialog } from './latex-dialog'
import { MathNode } from './math-node'
import { QuoteNode } from './quote-node'
import { MentionNode } from './mention-node'
import { VideoNode } from './video-node'

const lowlight = createLowlight(common)

// Patch the default Image extension to (a) carry an extra `attachment_id`
// attribute and (b) rewrite seed-data picsum URLs through `resolveImageSrc`.
const ImageWithAttachment = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
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
        parseHTML: (el) => resolveImageSrc(el.getAttribute('src')),
        renderHTML: (attrs) => {
          const src = attrs.src as string | undefined
          return src ? { src: resolveImageSrc(src) } : {}
        },
      },
    }
  },
})

export interface NotionEditorProps {
  value?: JSONContent
  onChange?: (value: JSONContent) => void
  editable?: boolean
  placeholder?: string
  className?: string
  /** Simplified toolbar without heading/lists/blockquote — used in DM. */
  variant?: 'full' | 'simple'
}

/**
 * Notion-like rich-text editor backed by TipTap (ProseMirror). The JSON
 * shape mirrors what the backend stores in `articles.content` / `messages.content`
 * — see docs/data-model.md.
 *
 * Implemented blocks: paragraph, headings, lists, code (lowlight), link,
 * image (uploaded via MinIO presigned URLs), and our custom `math` node
 * (KaTeX inline + block).
 *
 * Marks: bold, italic, underline, strike, code, link, highlight (multicolor),
 * textStyle/color.
 */
export function NotionEditor({
  value,
  onChange,
  editable = true,
  placeholder,
  className,
  variant = 'full',
}: NotionEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        codeBlock: false,
      }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        HTMLAttributes: { class: 'text-primary underline underline-offset-4' },
      }),
      ImageWithAttachment,
      CodeBlockLowlight.configure({ lowlight }),
      Underline,
      Highlight.configure({ multicolor: true }),
      TextStyle,
      Color.configure({ types: ['textStyle'] }),
      MathNode,
      MentionNode,
      CalloutNode,
      GifNode,
      VideoNode,
      QuoteNode,
      // Lets users paste raw markdown (e.g. an LLM proposal copied from the
      // AI panel) into the editor and have it auto-parse into ProseMirror
      // blocks (headings, lists, code, etc.).
      Markdown.configure({
        html: true,
        tightLists: true,
        bulletListMarker: '-',
        linkify: true,
        breaks: false,
        transformPastedText: true,
        transformCopiedText: false,
      }),
    ],
    content: value,
    editable,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: cn(
          'prose prose-sm dark:prose-invert max-w-none min-h-[200px] focus:outline-none',
          !editable && 'cursor-default min-h-0',
        ),
        ...(placeholder ? { 'data-placeholder': placeholder } : {}),
      },
    },
    onUpdate: ({ editor }) => {
      onChange?.(editor.getJSON())
    },
  })

  // Keep editor in sync if `editable` prop flips at runtime.
  useEffect(() => {
    if (editor && editor.isEditable !== editable) {
      editor.setEditable(editable)
    }
  }, [editor, editable])

  // Keep content in sync when an externally-controlled `value` changes
  // *and* the editor is not editable (read-view re-renders with new data).
  useEffect(() => {
    if (!editor) return
    if (editable) return
    if (!value) return
    const current = JSON.stringify(editor.getJSON())
    const next = JSON.stringify(value)
    if (current !== next) {
      editor.commands.setContent(value, false)
    }
  }, [editor, editable, value])

  if (!editor) {
    return (
      <div className={cn('rounded-md border border-border p-4', className)}>
        <div className="h-8 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  if (!editable) {
    // Read-only view: no chrome, just the prose.
    return (
      <div className={cn('rounded-md', className)}>
        <EditorContent editor={editor} />
      </div>
    )
  }

  return (
    <div className={cn('rounded-md border border-border bg-background', className)}>
      <Toolbar editor={editor} variant={variant} />
      <div className="p-4">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

const HIGHLIGHT_COLORS: { label: string; color: string | null; swatch: string }[] = [
  { label: 'Жёлтый', color: '#fef08a', swatch: '#fef08a' },
  { label: 'Зелёный', color: '#bbf7d0', swatch: '#bbf7d0' },
  { label: 'Розовый', color: '#fbcfe8', swatch: '#fbcfe8' },
  { label: 'Голубой', color: '#bae6fd', swatch: '#bae6fd' },
  { label: 'Без цвета', color: null, swatch: 'transparent' },
]

const TEXT_COLORS: { label: string; color: string | null; swatch: string }[] = [
  { label: 'По умолчанию', color: null, swatch: 'currentColor' },
  { label: 'Красный', color: '#dc2626', swatch: '#dc2626' },
  { label: 'Синий', color: '#2563eb', swatch: '#2563eb' },
  { label: 'Зелёный', color: '#16a34a', swatch: '#16a34a' },
  { label: 'Оранжевый', color: '#ea580c', swatch: '#ea580c' },
  { label: 'Фиолетовый', color: '#7c3aed', swatch: '#7c3aed' },
]

function Toolbar({
  editor,
  variant,
}: {
  editor: Editor
  variant: 'full' | 'simple'
}) {
  const isActive = (name: string, attrs?: Record<string, unknown>) =>
    editor.isActive(name, attrs)
  const { limits } = useAttachmentLimits()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState(false)
  const [latexOpen, setLatexOpen] = useState(false)

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadAttachment(file, { limits })
      // Cast: our extended Image schema adds `attachment_id`, but TipTap's
      // `setImage` typing only exposes the original {src, alt, title} keys.
      editor
        .chain()
        .focus()
        .setImage({
          src: result.url,
          attachment_id: result.attachment_id,
        } as unknown as { src: string })
        .run()
      toast.success('Изображение загружено')
    } catch (err) {
      if (err instanceof UploadValidationError) {
        toast.error(err.message)
      } else {
        const msg = err instanceof Error ? err.message : 'Не удалось загрузить файл'
        toast.error(msg)
      }
    } finally {
      setUploading(false)
    }
  }

  function handleInsertLatex(latex: string, display: boolean) {
    editor
      .chain()
      .focus()
      .insertContent({ type: 'math', attrs: { latex, display } })
      .run()
  }

  // Heading dropdown — determines current active level for label/icon.
  const currentHeadingIcon = (() => {
    if (isActive('heading', { level: 1 })) return <Heading1 className="h-4 w-4" />
    if (isActive('heading', { level: 2 })) return <Heading2 className="h-4 w-4" />
    if (isActive('heading', { level: 3 })) return <Heading3 className="h-4 w-4" />
    return <Pilcrow className="h-4 w-4" />
  })()

  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-border p-2">
      {/* Text style marks */}
      <ToolbarButton
        active={isActive('bold')}
        onClick={() => editor.chain().focus().toggleBold().run()}
        label="Полужирный"
      >
        <Bold className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        active={isActive('italic')}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        label="Курсив"
      >
        <Italic className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        active={isActive('underline')}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        label="Подчёркнутый"
      >
        <UnderlineIcon className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        active={isActive('strike')}
        onClick={() => editor.chain().focus().toggleStrike().run()}
        label="Зачёркнутый"
      >
        <Strikethrough className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        active={isActive('code')}
        onClick={() => editor.chain().focus().toggleCode().run()}
        label="Код (инлайн)"
      >
        <Code className="h-4 w-4" />
      </ToolbarButton>

      {/* Highlight color */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant={isActive('highlight') ? 'secondary' : 'ghost'}
            size="icon"
            aria-label="Выделение цветом"
            title="Выделение цветом"
          >
            <Highlighter className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {HIGHLIGHT_COLORS.map((c) => (
            <DropdownMenuItem
              key={c.label}
              onSelect={() => {
                if (c.color === null) {
                  editor.chain().focus().unsetHighlight().run()
                } else {
                  editor.chain().focus().toggleHighlight({ color: c.color }).run()
                }
              }}
            >
              <span
                className="inline-block h-4 w-4 rounded border border-border"
                style={{ background: c.swatch }}
              />
              <span>{c.label}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Text color */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant={isActive('textStyle', { color: /.+/ }) ? 'secondary' : 'ghost'}
            size="icon"
            aria-label="Цвет текста"
            title="Цвет текста"
          >
            <Palette className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {TEXT_COLORS.map((c) => (
            <DropdownMenuItem
              key={c.label}
              onSelect={() => {
                if (c.color === null) {
                  editor.chain().focus().unsetColor().run()
                } else {
                  editor.chain().focus().setColor(c.color).run()
                }
              }}
            >
              <span
                className="inline-block h-4 w-4 rounded border border-border"
                style={{
                  background: c.color ?? 'transparent',
                  color: c.color ?? 'currentColor',
                }}
              />
              <span>{c.label}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {variant === 'full' && (
        <>
          {/* Heading dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant={isActive('heading') ? 'secondary' : 'ghost'}
                size="sm"
                aria-label="Заголовок"
                title="Заголовок"
                className="gap-1 px-2"
              >
                {currentHeadingIcon}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem
                onSelect={() => editor.chain().focus().setParagraph().run()}
              >
                <Pilcrow className="h-4 w-4" />
                <span>Параграф</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  editor.chain().focus().toggleHeading({ level: 1 }).run()
                }
              >
                <Heading1 className="h-4 w-4" />
                <span>Заголовок 1</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  editor.chain().focus().toggleHeading({ level: 2 }).run()
                }
              >
                <Heading2 className="h-4 w-4" />
                <span>Заголовок 2</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  editor.chain().focus().toggleHeading({ level: 3 }).run()
                }
              >
                <Heading3 className="h-4 w-4" />
                <span>Заголовок 3</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <ToolbarButton
            active={isActive('bulletList')}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            label="Маркированный список"
          >
            <ListIcon className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton
            active={isActive('orderedList')}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            label="Нумерованный список"
          >
            <ListOrdered className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton
            active={isActive('blockquote')}
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
            label="Цитата"
          >
            <Quote className="h-4 w-4" />
          </ToolbarButton>
        </>
      )}

      {/* Insertions */}
      <ToolbarButton
        active={isActive('link')}
        onClick={() => {
          const previousUrl = editor.getAttributes('link').href as string | undefined
          const url = window.prompt('URL ссылки', previousUrl ?? 'https://')
          if (url === null) return
          if (url === '') {
            editor.chain().focus().extendMarkRange('link').unsetLink().run()
            return
          }
          editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run()
        }}
        label="Ссылка"
      >
        <LinkIcon className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        onClick={() => fileInputRef.current?.click()}
        label={uploading ? 'Загрузка…' : 'Изображение'}
        disabled={uploading}
      >
        {uploading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ImageIcon className="h-4 w-4" />
        )}
      </ToolbarButton>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFileSelected}
      />
      {variant === 'full' && (
        <>
          <ToolbarButton
            onClick={() => setLatexOpen(true)}
            label="Формула KaTeX"
          >
            <Sigma className="h-4 w-4" />
          </ToolbarButton>
          <LatexDialog
            open={latexOpen}
            onClose={() => setLatexOpen(false)}
            onInsert={handleInsertLatex}
          />
        </>
      )}
    </div>
  )
}

function ToolbarButton({
  active,
  onClick,
  label,
  children,
  disabled,
}: {
  active?: boolean
  onClick: () => void
  label: string
  children: React.ReactNode
  disabled?: boolean
}) {
  return (
    <Button
      type="button"
      variant={active ? 'secondary' : 'ghost'}
      size="icon"
      onClick={onClick}
      aria-label={label}
      title={label}
      disabled={disabled}
    >
      {children}
    </Button>
  )
}
