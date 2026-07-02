'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { api, extractErrorMessage } from '@/lib/api'

interface Props {
  articleId: string
  topicId: string
  isAdmin: boolean
  /** Optional custom trigger button props. Defaults to size="sm". */
  size?: 'sm' | 'default'
}

/**
 * Confirmation dialog for deleting an article. Author / moderator / admin can
 * soft-delete (archive); admin additionally gets a "hard delete" checkbox that
 * appends `?hard=true` to the DELETE call.
 */
export function DeleteArticleDialog({
  articleId,
  topicId,
  isAdmin,
  size = 'sm',
}: Props) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [hard, setHard] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function confirm() {
    setSubmitting(true)
    try {
      await api.delete(`articles/${articleId}`, {
        searchParams: hard && isAdmin ? { hard: 'true' } : undefined,
      })
      toast.success(hard && isAdmin ? 'Статья удалена' : 'Статья архивирована')
      setOpen(false)
      router.push(`/topics/${topicId}/articles` as never)
    } catch (err) {
      toast.error(await extractErrorMessage(err, 'Не удалось удалить статью'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="destructive"
          size={size}
          data-testid="delete-article-button"
        >
          Удалить
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Удалить статью?</DialogTitle>
          <DialogDescription>
            {hard && isAdmin
              ? 'Статья будет удалена безвозвратно — без возможности восстановления.'
              : 'Статья будет архивирована. Восстановить её сможет автор или модератор.'}
          </DialogDescription>
        </DialogHeader>

        {isAdmin && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={hard}
              onChange={(e) => setHard(e.target.checked)}
              className="h-4 w-4 rounded border-input"
              data-testid="delete-article-hard"
            />
            <span>Полное удаление (без возможности восстановления)</span>
          </label>
        )}

        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={submitting}
          >
            Отмена
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={confirm}
            disabled={submitting}
            data-testid="delete-article-confirm"
          >
            {submitting ? 'Удаляем…' : hard && isAdmin ? 'Удалить навсегда' : 'Архивировать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
