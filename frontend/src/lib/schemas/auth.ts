import { z } from 'zod'

export const loginSchema = z.object({
  username_or_email: z.string().min(3, 'Минимум 3 символа').max(254),
  password: z.string().min(8, 'Минимум 8 символов').max(128),
})
export type LoginInput = z.infer<typeof loginSchema>

export const registerSchema = z
  .object({
    username: z
      .string()
      .min(3, 'Минимум 3 символа')
      .max(32)
      .regex(/^[a-zA-Z0-9_]+$/, 'Только латиница, цифры и _'),
    email: z.string().email('Некорректный email'),
    password: z.string().min(8, 'Минимум 8 символов').max(128),
    passwordConfirm: z.string(),
  })
  .refine((d) => d.password === d.passwordConfirm, {
    message: 'Пароли не совпадают',
    path: ['passwordConfirm'],
  })
export type RegisterInput = z.infer<typeof registerSchema>

export const SOCIAL_KEYS = [
  'github',
  'twitter',
  'mastodon',
  'scholar',
  'linkedin',
  'web',
] as const

export type SocialKey = (typeof SOCIAL_KEYS)[number]

const optionalUrl = z
  .string()
  .url('Должен быть корректным URL')
  .max(500)
  .optional()
  .or(z.literal(''))

export const profileUpdateSchema = z.object({
  display_name: z.string().max(100).optional().or(z.literal('')),
  bio: z.string().max(2000).optional().or(z.literal('')),
  avatar_url: optionalUrl,
  orcid: z
    .string()
    .regex(/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/, 'Формат: ####-####-####-###[0-9X]')
    .optional()
    .or(z.literal('')),
  locale: z.enum(['ru', 'en']).optional(),
  timezone: z.string().max(50).optional().or(z.literal('')),
  social_links: z
    .object({
      github: optionalUrl,
      twitter: optionalUrl,
      mastodon: optionalUrl,
      scholar: optionalUrl,
      linkedin: optionalUrl,
      web: optionalUrl,
    })
    .partial()
    .optional(),
})
export type ProfileUpdateInput = z.infer<typeof profileUpdateSchema>
