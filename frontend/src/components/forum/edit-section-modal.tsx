'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import type { SectionRead } from '@/lib/types'

const ICON_OPTIONS = [
  'Brain',
  'Microscope',
  'Activity',
  'Atom',
  'Cpu',
  'FlaskConical',
  'Layers',
  'Sparkles',
  'BookOpen',
  'Lightbulb',
] as const

export interface EditSectionModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  section: SectionRead
}

export function EditSectionModal({
  open,
  onOpenChange,
  section,
}: EditSectionModalProps) {
  const qc = useQueryClient()
  const [title, setTitle] = useState(section.title)
  const [description, setDescription] = useState(section.description ?? '')
  const [icon, setIcon] = useState<string>(section.icon ?? '')
  const [position, setPosition] = useState<number>(section.position)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setTitle(section.title)
      setDescription(section.description ?? '')
      setIcon(section.icon ?? '')
      setPosition(section.position)
      setError(null)
    }
  }, [open, section])

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(`sections/${section.slug}`, { json: body }).json<SectionRead>(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['section', section.slug] })
      void qc.invalidateQueries({ queryKey: ['sections'] })
      onOpenChange(false)
    },
    onError: async (err) => {
      setError(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    const trimmed = title.trim()
    if (!trimmed) {
      setError('Введите название раздела')
      return
    }
    await mutation.mutateAsync({
      title: trimmed,
      description: description.trim() || null,
      icon: icon.trim() || null,
      position,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Редактировать раздел</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="section-title" className="text-sm font-medium">
              Название
            </label>
            <Input
              id="section-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              data-testid="edit-section-title"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="section-desc" className="text-sm font-medium">
              Описание
            </label>
            <Textarea
              id="section-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="section-icon" className="text-sm font-medium">
                Иконка
              </label>
              <select
                id="section-icon"
                value={icon}
                onChange={(e) => setIcon(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">— без иконки —</option>
                {ICON_OPTIONS.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="section-position" className="text-sm font-medium">
                Позиция
              </label>
              <Input
                id="section-position"
                type="number"
                value={position}
                onChange={(e) => setPosition(Number(e.target.value) || 0)}
              />
            </div>
          </div>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending}
              data-testid="edit-section-submit"
            >
              {mutation.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
