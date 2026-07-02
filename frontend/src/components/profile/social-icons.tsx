'use client'

import {
  Github,
  Globe,
  GraduationCap,
  Linkedin,
  MessageCircle,
  Twitter,
} from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'

import type { SocialKey } from '@/lib/schemas/auth'

interface IconInfo {
  Icon: ComponentType<SVGProps<SVGSVGElement>>
  label: string
}

export const SOCIAL_ICON_META: Record<SocialKey, IconInfo> = {
  github: { Icon: Github, label: 'GitHub' },
  twitter: { Icon: Twitter, label: 'X / Twitter' },
  mastodon: { Icon: MessageCircle, label: 'Mastodon' },
  scholar: { Icon: GraduationCap, label: 'Google Scholar' },
  linkedin: { Icon: Linkedin, label: 'LinkedIn' },
  web: { Icon: Globe, label: 'Сайт' },
}
