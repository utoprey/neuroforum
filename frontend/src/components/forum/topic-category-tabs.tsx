'use client'

import {
  Megaphone,
  MessagesSquare,
  LifeBuoy,
  Waves,
  type LucideIcon,
} from 'lucide-react'

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { TOPIC_KIND_LABEL, type TopicKind } from '@/lib/types'

const KIND_ICON: Record<TopicKind, LucideIcon> = {
  news: Megaphone,
  discussion: MessagesSquare,
  help: LifeBuoy,
  flood: Waves,
}

const ORDER: TopicKind[] = ['news', 'discussion', 'help', 'flood']

export interface TopicCategoryTabsProps {
  value: TopicKind
  onChange: (kind: TopicKind) => void
}

/** 4-category strip used at the top of a section page: news / discussions /
 *  help / flood. Controlled by the parent (typically via ?kind= URL param). */
export function TopicCategoryTabs({ value, onChange }: TopicCategoryTabsProps) {
  return (
    <Tabs
      value={value}
      onValueChange={(v) => onChange(v as TopicKind)}
      className="w-full"
    >
      <TabsList
        className="grid h-auto w-full grid-cols-2 gap-1 p-1 sm:grid-cols-4"
        data-testid="topic-category-tabs"
      >
        {ORDER.map((kind) => {
          const Icon = KIND_ICON[kind]
          return (
            <TabsTrigger
              key={kind}
              value={kind}
              data-testid={`topic-tab-${kind}`}
              className="flex items-center justify-center gap-2 py-2"
            >
              <Icon className="h-4 w-4" />
              <span>{TOPIC_KIND_LABEL[kind]}</span>
            </TabsTrigger>
          )
        })}
      </TabsList>
    </Tabs>
  )
}
