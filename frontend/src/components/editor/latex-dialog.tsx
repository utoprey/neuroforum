'use client'

import { useEffect, useMemo, useState } from 'react'
import { BlockMath, InlineMath } from 'react-katex'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

interface LatexDialogProps {
  open: boolean
  onClose: () => void
  initialLatex?: string
  initialDisplay?: boolean
  onInsert: (latex: string, display: boolean) => void
}

/**
 * Modal dialog for entering a LaTeX formula with KaTeX live preview.
 *
 * Inline mode (display=false) renders semantically as a block math node
 * with `display=false` — MathNodeView renders it via `as: 'span'`. This
 * is a compromise so we don't have to change MathNode's `group: 'block'`
 * (changing it would break existing documents).
 */
export function LatexDialog({
  open,
  onClose,
  initialLatex = '',
  initialDisplay = true,
  onInsert,
}: LatexDialogProps) {
  const [latex, setLatex] = useState(initialLatex)
  const [display, setDisplay] = useState(initialDisplay)

  // Reset state every time dialog opens with fresh initial values.
  useEffect(() => {
    if (open) {
      setLatex(initialLatex)
      setDisplay(initialDisplay)
    }
  }, [open, initialLatex, initialDisplay])

  const preview = useMemo(() => {
    const trimmed = latex.trim()
    if (!trimmed) {
      return (
        <span className="italic text-muted-foreground">
          Введите формулу для предпросмотра
        </span>
      )
    }
    try {
      return display ? <BlockMath math={latex} /> : <InlineMath math={latex} />
    } catch (e) {
      return (
        <span className="text-destructive">
          Ошибка в формуле: {e instanceof Error ? e.message : String(e)}
        </span>
      )
    }
  }, [latex, display])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Формула LaTeX</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="flex gap-2">
            <Button
              type="button"
              variant={display ? 'default' : 'outline'}
              size="sm"
              onClick={() => setDisplay(true)}
            >
              Блочная (display)
            </Button>
            <Button
              type="button"
              variant={!display ? 'default' : 'outline'}
              size="sm"
              onClick={() => setDisplay(false)}
            >
              Строчная (inline)
            </Button>
          </div>
          <Textarea
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            rows={4}
            placeholder={'\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}'}
            className="font-mono text-sm"
            autoFocus
          />
          <div className="flex min-h-[60px] items-center justify-center rounded-md border bg-muted/30 p-3">
            {preview}
          </div>
          <p className="text-xs text-muted-foreground">
            Поддерживается синтаксис KaTeX. Подсказки:{' '}
            <code className="font-mono">{'\\frac{a}{b}'}</code>,{' '}
            <code className="font-mono">\sum</code>,{' '}
            <code className="font-mono">\int</code>,{' '}
            <code className="font-mono">^_</code> для степени/индекса.
          </p>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button
            type="button"
            onClick={() => {
              if (!latex.trim()) return
              onInsert(latex, display)
              onClose()
            }}
            disabled={!latex.trim()}
          >
            Вставить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
