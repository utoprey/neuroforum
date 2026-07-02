'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api, extractErrorMessage } from '@/lib/api'
import {
  AI_PROPOSAL_ACTION_LABEL,
  AI_PROPOSAL_ACTIONS,
  type AIProposalAction,
  type ArticleAIProposal,
} from '@/lib/types'

interface Props {
  articleId: string
}

const PROMPT_MAX = 500

/**
 * "AI обзор" trigger button — opens a dialog where the author / moderator
 * picks an action (`draft | expand | rephrase | …`) and optionally adds a
 * free-form hint. POSTs to `articles/{id}/ai-proposals` and invalidates the
 * pending-proposals query so `<AIProposalsPanel>` re-renders.
 */
export function AIReviewButton({ articleId }: Props) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<AIProposalAction>('expand')
  const [prompt, setPrompt] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      api
        .post(`articles/${articleId}/ai-proposals`, {
          json: {
            action,
            prompt: prompt.trim() || null,
          },
        })
        .json<ArticleAIProposal>(),
    onSuccess: async () => {
      toast.success('AI-предложение создано')
      await qc.invalidateQueries({
        queryKey: ['article', articleId, 'ai-proposals'],
      })
      setPrompt('')
      setOpen(false)
    },
    onError: async (err) => {
      toast.error(
        await extractErrorMessage(err, 'Не удалось запросить AI-обзор'),
      )
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="ai-review-button"
        >
          <Sparkles className="h-4 w-4" />
          AI обзор
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>AI обзор статьи</DialogTitle>
          <DialogDescription>
            Обзор сгенерирует ваша LLM через OpenRouter (укажите ключ в{" "}
            <a href="/me/credentials" className="underline">
              /me/credentials
            </a>
            ). Результат появится в блоке «AI обзоры» под статьёй; оригинал не
            меняется.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="ai-action" className="text-sm font-medium">
              Тип обзора
            </label>
            <Select
              value={action}
              onValueChange={(v) => setAction(v as AIProposalAction)}
            >
              <SelectTrigger id="ai-action" data-testid="ai-action-trigger">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AI_PROPOSAL_ACTIONS.map((a) => (
                  <SelectItem key={a} value={a}>
                    {AI_PROPOSAL_ACTION_LABEL[a]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="ai-prompt" className="text-sm font-medium">
              Уточнение (опц.)
            </label>
            <Textarea
              id="ai-prompt"
              rows={3}
              value={prompt}
              maxLength={PROMPT_MAX}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Например: сократи введение и добавь ссылки на исходники"
            />
            <span className="text-xs text-muted-foreground">
              {prompt.length}/{PROMPT_MAX}
            </span>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={createMutation.isPending}
          >
            Отмена
          </Button>
          <Button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            data-testid="ai-review-submit"
          >
            {createMutation.isPending ? 'Запрашиваем…' : 'Запросить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
