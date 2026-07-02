'use client'

import { Copy, Mail, Send, Share2, Twitter } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export interface ShareDropdownProps {
  /** URL to share. Defaults to the current page URL on click. */
  url?: string
  /** Title/subject for the share intent. */
  title?: string
  /**
   * Optional element label. When `compact`, render just the icon button;
   * otherwise show icon + "Поделиться" text.
   */
  compact?: boolean
}

function resolveUrl(url?: string): string {
  if (url) return url
  if (typeof window !== 'undefined') return window.location.href
  return ''
}

export function ShareDropdown({
  url,
  title = '',
  compact = true,
}: ShareDropdownProps) {
  const handleCopy = async () => {
    const target = resolveUrl(url)
    try {
      await navigator.clipboard.writeText(target)
      toast.success('Ссылка скопирована')
    } catch {
      toast.error('Не удалось скопировать ссылку')
    }
  }

  const open = (href: string) => {
    window.open(href, '_blank', 'noopener,noreferrer')
  }

  const handleTelegram = () => {
    const target = resolveUrl(url)
    open(
      `https://t.me/share/url?url=${encodeURIComponent(target)}&text=${encodeURIComponent(title)}`,
    )
  }

  const handleVk = () => {
    const target = resolveUrl(url)
    open(`https://vk.com/share.php?url=${encodeURIComponent(target)}`)
  }

  const handleTwitter = () => {
    const target = resolveUrl(url)
    open(
      `https://twitter.com/intent/tweet?url=${encodeURIComponent(target)}&text=${encodeURIComponent(title)}`,
    )
  }

  const handleEmail = () => {
    const target = resolveUrl(url)
    window.location.href = `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(target)}`
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size={compact ? 'icon' : 'sm'}
          aria-label="Поделиться"
          data-testid="share-button"
        >
          <Share2 className="h-4 w-4" />
          {!compact && <span>Поделиться</span>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Поделиться</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void handleCopy()}>
          <Copy className="h-4 w-4" />
          Скопировать ссылку
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleTelegram}>
          <Send className="h-4 w-4" />
          Telegram
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleVk}>
          <span className="inline-flex h-4 w-4 items-center justify-center text-[10px] font-bold">
            VK
          </span>
          VKontakte
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleTwitter}>
          <Twitter className="h-4 w-4" />
          X / Twitter
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleEmail}>
          <Mail className="h-4 w-4" />
          Email
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
