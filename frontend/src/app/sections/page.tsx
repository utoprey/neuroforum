'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import type { SectionRead } from '@/lib/types'

export default function SectionsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['sections'],
    queryFn: () => api.get('sections').json<SectionRead[]>(),
  })

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-3xl font-semibold tracking-tight">Разделы</h1>
      {isLoading && (
        <p className="text-muted-foreground">Загружаем разделы…</p>
      )}
      {isError && (
        <p className="text-destructive">Не удалось загрузить список разделов.</p>
      )}
      {data && data.length === 0 && (
        <p className="text-muted-foreground">
          Разделов пока нет. Администратор может создать их через API.
        </p>
      )}
      {data && data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data
            .slice()
            .sort((a, b) => a.position - b.position)
            .map((s) => (
              <Link
                key={s.id}
                href={`/sections/${s.slug}/topics` as never}
                className="block"
                data-testid="section-card"
              >
                <Card className="h-full transition-colors hover:bg-accent">
                  <CardHeader>
                    <CardTitle className="text-lg">
                      {s.icon ? <span className="mr-2">{s.icon}</span> : null}
                      {s.title}
                    </CardTitle>
                    {s.description && (
                      <CardDescription>{s.description}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent>
                    <span className="text-sm text-muted-foreground">
                      /{s.slug}
                    </span>
                  </CardContent>
                </Card>
              </Link>
            ))}
        </div>
      )}
    </div>
  )
}
