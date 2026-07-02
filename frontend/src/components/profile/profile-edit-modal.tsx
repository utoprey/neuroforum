'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
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
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SOCIAL_ICON_META } from '@/components/profile/social-icons'
import { api, extractErrorMessage } from '@/lib/api'
import { profileUpdateSchema, SOCIAL_KEYS } from '@/lib/schemas/auth'
import type { ProfileRead } from '@/lib/types'

export interface ProfileEditModalProps {
  profile: ProfileRead | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface FormState {
  display_name: string
  bio: string
  avatar_url: string
  orcid: string
  locale: 'ru' | 'en'
  timezone: string
  social_links: Record<string, string>
}

function makeInitial(profile: ProfileRead | null): FormState {
  const links: Record<string, string> = {}
  for (const key of SOCIAL_KEYS) {
    const v = profile?.social_links?.[key]
    links[key] = typeof v === 'string' ? v : ''
  }
  return {
    display_name: profile?.display_name ?? '',
    bio: profile?.bio ?? '',
    avatar_url: profile?.avatar_url ?? '',
    orcid: profile?.orcid ?? '',
    locale: profile?.locale === 'en' ? 'en' : 'ru',
    timezone: profile?.timezone ?? 'UTC',
    social_links: links,
  }
}

export function ProfileEditModal({
  profile,
  open,
  onOpenChange,
}: ProfileEditModalProps) {
  const qc = useQueryClient()
  const [state, setState] = useState<FormState>(() => makeInitial(profile))
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  // Reset state when the dialog opens with a (possibly) fresh profile.
  function handleOpenChange(next: boolean) {
    if (next) setState(makeInitial(profile))
    setError(null)
    setFieldErrors({})
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch('users/me/profile', { json: body }).json<ProfileRead>(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['users', 'me'] })
      toast.success('Профиль сохранён')
      onOpenChange(false)
    },
    onError: async (err) => {
      const msg = await extractErrorMessage(err, 'Не удалось сохранить')
      setError(msg)
      toast.error(msg)
    },
  })

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setFieldErrors({})

    // Drop empty values from social_links before validating.
    const cleanedLinks: Record<string, string> = {}
    for (const [k, v] of Object.entries(state.social_links)) {
      if (v.trim()) cleanedLinks[k] = v.trim()
    }

    const raw = {
      display_name: state.display_name,
      bio: state.bio,
      avatar_url: state.avatar_url,
      orcid: state.orcid,
      locale: state.locale,
      timezone: state.timezone,
      social_links: cleanedLinks,
    }
    const parsed = profileUpdateSchema.safeParse(raw)
    if (!parsed.success) {
      const fe: Record<string, string> = {}
      for (const issue of parsed.error.issues) {
        const key = issue.path.join('.')
        if (key && !fe[key]) fe[key] = issue.message
      }
      setFieldErrors(fe)
      return
    }

    // Backend expects null for cleared optional fields; map empty strings -> null.
    const payload: Record<string, unknown> = {
      display_name: parsed.data.display_name?.trim() || null,
      bio: parsed.data.bio?.trim() || null,
      avatar_url: parsed.data.avatar_url?.trim() || null,
      orcid: parsed.data.orcid?.trim() || null,
      locale: parsed.data.locale ?? null,
      timezone: parsed.data.timezone?.trim() || null,
      social_links: cleanedLinks,
    }
    await mutation.mutateAsync(payload)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Редактирование профиля</DialogTitle>
          <DialogDescription>
            Все поля опциональны. ORCID должен быть в формате
            ####-####-####-###[0-9X].
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <Field
            id="display_name"
            label="Имя для отображения"
            value={state.display_name}
            onChange={(v) => setState((s) => ({ ...s, display_name: v }))}
            error={fieldErrors.display_name}
            maxLength={100}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="bio" className="text-sm font-medium">
              Био
            </label>
            <Textarea
              id="bio"
              rows={4}
              maxLength={1000}
              value={state.bio}
              onChange={(e) => setState((s) => ({ ...s, bio: e.target.value }))}
            />
            {fieldErrors.bio && (
              <p className="text-xs text-destructive">{fieldErrors.bio}</p>
            )}
          </div>
          <Field
            id="avatar_url"
            label="URL аватара"
            placeholder="https://…"
            value={state.avatar_url}
            onChange={(v) => setState((s) => ({ ...s, avatar_url: v }))}
            error={fieldErrors.avatar_url}
          />
          <Field
            id="orcid"
            label="ORCID"
            placeholder="0000-0000-0000-0000"
            value={state.orcid}
            onChange={(v) => setState((s) => ({ ...s, orcid: v }))}
            error={fieldErrors.orcid}
          />
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="locale" className="text-sm font-medium">
                Язык
              </label>
              <select
                id="locale"
                value={state.locale}
                onChange={(e) =>
                  setState((s) => ({
                    ...s,
                    locale: e.target.value === 'en' ? 'en' : 'ru',
                  }))
                }
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="ru">Русский</option>
                <option value="en">English</option>
              </select>
            </div>
            <Field
              id="timezone"
              label="Часовой пояс"
              placeholder="UTC"
              value={state.timezone}
              onChange={(v) => setState((s) => ({ ...s, timezone: v }))}
              error={fieldErrors.timezone}
            />
          </div>

          <fieldset className="flex flex-col gap-2 rounded-md border border-border p-3">
            <legend className="px-1 text-sm font-medium">
              Социальные сети
            </legend>
            {SOCIAL_KEYS.map((key) => {
              const meta = SOCIAL_ICON_META[key]
              const Icon = meta.Icon
              return (
                <div
                  key={key}
                  className="flex items-center gap-2"
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <Input
                    id={`social-${key}`}
                    placeholder={meta.label}
                    value={state.social_links[key] ?? ''}
                    onChange={(e) =>
                      setState((s) => ({
                        ...s,
                        social_links: {
                          ...s.social_links,
                          [key]: e.target.value,
                        },
                      }))
                    }
                  />
                </div>
              )
            })}
            {Object.entries(fieldErrors)
              .filter(([k]) => k.startsWith('social_links.'))
              .map(([k, v]) => (
                <p key={k} className="text-xs text-destructive">
                  {k.replace('social_links.', '')}: {v}
                </p>
              ))}
          </fieldset>

          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter className="mt-3 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
  error,
  placeholder,
  maxLength,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  error?: string
  placeholder?: string
  maxLength?: number
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
