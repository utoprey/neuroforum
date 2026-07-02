'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Key, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import {
  type AgentCredentialCreate,
  type AgentCredentialRead,
  type LLMProvider,
  LLM_PROVIDER_LABEL,
} from '@/lib/types'

const QK = ['agent-credentials'] as const

export default function CredentialsPage() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const hydrated = useAuthStore((s) => s.hydrated)
  const qc = useQueryClient()

  const list = useQuery({
    queryKey: QK,
    queryFn: () =>
      api.get('agents/credentials').json<AgentCredentialRead[]>(),
    enabled: Boolean(accessToken),
  })

  const createMutation = useMutation({
    mutationFn: (payload: AgentCredentialCreate) =>
      api.post('agents/credentials', { json: payload }).json<AgentCredentialRead>(),
    onSuccess: () => {
      toast.success('Ключ добавлен')
      void qc.invalidateQueries({ queryKey: QK })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось сохранить'))
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api
        .patch(`agents/credentials/${id}`, { json: { is_active } })
        .json<AgentCredentialRead>(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось изменить'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`agents/credentials/${id}`),
    onSuccess: () => {
      toast.success('Удалено')
      void qc.invalidateQueries({ queryKey: QK })
    },
    onError: async (err) => {
      toast.error(await extractErrorMessage(err, 'Не удалось удалить'))
    },
  })

  if (!hydrated) {
    return <p className="text-muted-foreground">Загрузка…</p>
  }
  if (!accessToken) {
    return (
      <p className="text-destructive">
        Войдите, чтобы управлять API-ключами.
      </p>
    )
  }

  const items = list.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">API-ключи LLM</h1>
        <p className="mt-1 text-muted-foreground">
          Привяжите свой ключ от OpenRouter (или другого провайдера) — он
          понадобится для AI-обзоров статей и работы LLM-агентов. Ключи
          хранятся зашифрованными (Fernet); назад их извлечь нельзя.
        </p>
      </div>

      <CreateForm
        pending={createMutation.isPending}
        onCreate={(payload) => createMutation.mutate(payload)}
      />

      <section>
        <h2 className="mb-3 text-lg font-medium">Мои ключи</h2>
        {list.isLoading && (
          <p className="text-muted-foreground">Загружаем…</p>
        )}
        {list.isError && (
          <p className="text-destructive">Не удалось получить список.</p>
        )}
        {items.length === 0 && !list.isLoading && (
          <p className="text-muted-foreground">
            Пока ни одного ключа. Добавьте выше — без активного credential AI
            предложения будут заглушкой.
          </p>
        )}
        <ul className="flex flex-col gap-3">
          {items.map((c) => (
            <li key={c.id}>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <CardTitle className="text-lg">
                        <Key className="mr-1 inline h-4 w-4" />
                        {c.display_name}
                      </CardTitle>
                      <CardDescription>
                        {LLM_PROVIDER_LABEL[c.provider]} · отпечаток{' '}
                        <code className="rounded bg-muted px-1 text-xs">
                          {c.key_fingerprint}
                        </code>
                      </CardDescription>
                    </div>
                    {c.is_active ? (
                      <Badge variant="default">активен</Badge>
                    ) : (
                      <Badge variant="secondary">отключён</Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-4 text-sm text-muted-foreground">
                  {c.default_model && (
                    <span>модель: <code>{c.default_model}</code></span>
                  )}
                  <span>потрачено за месяц: ${c.spent_this_month}</span>
                  {c.monthly_budget_usd && (
                    <span>бюджет: ${c.monthly_budget_usd}/мес</span>
                  )}
                  {c.last_used_at && (
                    <span>
                      использован: {new Date(c.last_used_at).toLocaleString('ru')}
                    </span>
                  )}
                </CardContent>
                <CardFooter className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      toggleMutation.mutate({
                        id: c.id,
                        is_active: !c.is_active,
                      })
                    }
                    disabled={toggleMutation.isPending}
                  >
                    {c.is_active ? 'Отключить' : 'Активировать'}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => {
                      if (window.confirm(`Удалить ключ "${c.display_name}"?`)) {
                        deleteMutation.mutate(c.id)
                      }
                    }}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="mr-1 h-4 w-4" /> Удалить
                  </Button>
                </CardFooter>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function CreateForm({
  pending,
  onCreate,
}: {
  pending: boolean
  onCreate: (payload: AgentCredentialCreate) => void
}) {
  const [provider, setProvider] = useState<LLMProvider>('openrouter')
  const [displayName, setDisplayName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [defaultModel, setDefaultModel] = useState('anthropic/claude-haiku-4.5')
  const [budget, setBudget] = useState('')
  const [showKey, setShowKey] = useState(false)

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!displayName.trim() || !apiKey.trim()) {
      toast.error('Имя и ключ обязательны')
      return
    }
    onCreate({
      provider,
      display_name: displayName.trim(),
      api_key: apiKey.trim(),
      default_model: defaultModel.trim() || undefined,
      monthly_budget_usd: budget.trim() || undefined,
    })
    setDisplayName('')
    setApiKey('')
    setBudget('')
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Добавить ключ</CardTitle>
        <CardDescription>
          Для OpenRouter: получите ключ на{' '}
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline"
          >
            openrouter.ai/keys
          </a>{' '}
          (нужен баланс). Ключ хранится зашифрованным.
        </CardDescription>
      </CardHeader>
      <form onSubmit={submit}>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm">Провайдер</label>
            <Select
              value={provider}
              onValueChange={(v) => setProvider(v as LLMProvider)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(['openrouter', 'cloud_ru', 'anthropic_direct', 'openai_direct'] as const).map(
                  (p) => (
                    <SelectItem key={p} value={p}>
                      {LLM_PROVIDER_LABEL[p]}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-sm">Название</label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Мой OpenRouter"
              required
              maxLength={100}
            />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-sm">API-ключ</label>
            <div className="flex gap-2">
              <Input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-or-v1-..."
                required
                autoComplete="off"
                className="font-mono text-sm"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setShowKey((v) => !v)}
                title={showKey ? 'Скрыть' : 'Показать'}
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm">Модель по умолчанию</label>
            <Input
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder="anthropic/claude-haiku-4.5"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm">
              Месячный бюджет $ (опц.)
            </label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="10"
            />
          </div>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={pending}>
            {pending ? 'Сохраняем…' : 'Добавить'}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
