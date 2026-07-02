'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState, type FormEvent } from 'react'

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
import { api, extractErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/lib/auth-store'
import { registerSchema } from '@/lib/schemas/auth'
import type { TokenPair, UserRead } from '@/lib/types'

type FieldKey = 'username' | 'email' | 'password' | 'passwordConfirm'

export default function RegisterPage() {
  const router = useRouter()
  const setTokens = useAuthStore((s) => s.setTokens)
  const setUser = useAuthStore((s) => s.setUser)
  const [errors, setErrors] = useState<Partial<Record<FieldKey, string>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const parsed = registerSchema.safeParse({
      username: form.get('username'),
      email: form.get('email'),
      password: form.get('password'),
      passwordConfirm: form.get('passwordConfirm'),
    })
    if (!parsed.success) {
      const fieldErrors: typeof errors = {}
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as FieldKey | undefined
        if (key && !fieldErrors[key]) fieldErrors[key] = issue.message
      }
      setErrors(fieldErrors)
      return
    }
    setErrors({})
    setSubmitting(true)
    try {
      // 1. Create user. Backend route is POST /users/ (trailing slash matters
      //    on FastAPI's APIRouter mount). ky strips leading slashes, so we
      //    pass the explicit trailing slash here.
      await api
        .post('users/', {
          json: {
            username: parsed.data.username,
            email: parsed.data.email,
            password: parsed.data.password,
          },
        })
        .json()
      // 2. Auto-login
      const tokens = await api
        .post('auth/login', {
          json: {
            username_or_email: parsed.data.username,
            password: parsed.data.password,
          },
        })
        .json<TokenPair>()
      setTokens({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      })
      const me = await api.get('users/me').json<UserRead>()
      setUser(me)
      router.push('/profile')
      router.refresh()
    } catch (err) {
      setFormError(await extractErrorMessage(err, 'Не удалось создать аккаунт'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Регистрация</CardTitle>
          <CardDescription>
            Создайте аккаунт, чтобы писать статьи и обсуждать.
          </CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit}>
          <CardContent className="flex flex-col gap-4">
            <Field
              id="username"
              name="username"
              label="Имя пользователя"
              autoComplete="username"
              error={errors.username}
            />
            <Field
              id="email"
              name="email"
              type="email"
              label="Email"
              autoComplete="email"
              error={errors.email}
            />
            <Field
              id="password"
              name="password"
              type="password"
              label="Пароль"
              autoComplete="new-password"
              error={errors.password}
            />
            <Field
              id="passwordConfirm"
              name="passwordConfirm"
              type="password"
              label="Подтверждение пароля"
              autoComplete="new-password"
              error={errors.passwordConfirm}
            />
            {formError && (
              <p className="text-sm text-destructive" role="alert">
                {formError}
              </p>
            )}
          </CardContent>
          <CardFooter className="flex flex-col items-stretch gap-3">
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Создаём…' : 'Создать аккаунт'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Уже есть аккаунт?{' '}
              <Link href="/login" className="text-primary hover:underline">
                Войти
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}

function Field({
  id,
  name,
  label,
  type = 'text',
  autoComplete,
  error,
}: {
  id: string
  name: string
  label: string
  type?: string
  autoComplete?: string
  error?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input id={id} name={name} type={type} autoComplete={autoComplete} required />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
