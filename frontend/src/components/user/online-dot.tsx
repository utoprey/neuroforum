'use client'

import { cn } from '@/lib/utils'

interface OnlineDotProps {
  isOnline?: boolean | null
  className?: string
}

/**
 * Small green dot used as an avatar adornment when the user is currently
 * online. Renders `null` when offline so callers don't need extra wrapper
 * markup. Expects the parent element to be `position: relative`.
 */
export function OnlineDot({ isOnline, className }: OnlineDotProps) {
  if (!isOnline) return null
  return (
    <span
      aria-label="онлайн"
      role="status"
      className={cn(
        'absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full border-2 border-background bg-emerald-500',
        className,
      )}
    />
  )
}
