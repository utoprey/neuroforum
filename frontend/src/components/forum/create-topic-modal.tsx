'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import {
  TOPIC_KIND_LABEL,
  type TopicKind,
  type TopicRead,
} from '@/lib/types'

export interface CreateTopicModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  sectionSlug: string
  kind: TopicKind
}

export function CreateTopicModal({
  open,
  onOpenChange,
  sectionSlug,
  kind,
}: CreateTopicModalProps) {
  const router = useRouter()
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!open) {
      setTitle('')
      setSlug('')
      setDescription('')
      setError(null)
    }
  }, [open])

  const mutation = useMutation({
    mutationFn: (body: {
      title: string
      slug?: string | null
      description?: string | null
      kind: TopicKind
    }) =>
      api
        .post(`sections/${sectionSlug}/topics`, { json: body })
        .json<TopicRead>(),
    onSuccess: (topic) => {
      void qc.invalidateQueries({ queryKey: ['section', sectionSlug, 'topics'] })
      onOpenChange(false)
      router.push(`/topics/${topic.id}/articles` as never)
    },
    onError: async (err) => {
      setError(await extractErrorMessage(err, 'Не удалось создать тему'))
    },
  })

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    const t = title.trim()
    if (!t) {
      setError('Введите название темы')
      return
    }
    await mutation.mutateAsync({
      title: t,
      slug: slug.trim() || null,
      description: description.trim() || null,
      kind,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новая тема</DialogTitle>
          <DialogDescription>
            Категория: <strong>{TOPIC_KIND_LABEL[kind]}</strong>
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="topic-title" className="text-sm font-medium">
              Название
            </label>
            <Input
              id="topic-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              data-testid="create-topic-title"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="topic-slug" className="text-sm font-medium">
              Slug (опционально)
            </label>
            <Input
              id="topic-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="auto из title если оставить пустым"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="topic-desc" className="text-sm font-medium">
              Описание (опционально)
            </label>
            <Textarea
              id="topic-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
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
              data-testid="create-topic-submit"
            >
              {mutation.isPending ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
