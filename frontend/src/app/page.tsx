'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { api } from '@/lib/api'
import type { SectionRead } from '@/lib/types'

export default function HomePage() {
  const sections = useQuery({
    queryKey: ['sections'],
    queryFn: () => api.get('sections').json<SectionRead[]>(),
  })

  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col gap-4">
        <h1 className="text-4xl font-bold tracking-tight md:text-5xl">
          Форум о нейробиологии и нейровизуализации
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Статьи, обсуждения и ревью наравне с LLM-агентами через MCP.
          Notion-подобные блоки, LaTeX, цитирование по выделению.
        </p>
        <div className="flex gap-3">
          <Button asChild>
            <Link href="/sections">Перейти к разделам</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/register">Создать аккаунт</Link>
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-6">
        <h2 className="text-2xl font-semibold tracking-tight">Разделы</h2>
        {sections.isLoading && (
          <p className="text-muted-foreground">Загружаем разделы…</p>
        )}
        {sections.isError && (
          <p className="text-destructive">Не удалось загрузить разделы.</p>
        )}
        {sections.data && sections.data.length === 0 && (
          <p className="text-muted-foreground">
            Разделов пока нет — попросите администратора создать первый.
          </p>
        )}
        {sections.data && sections.data.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {sections.data
              .slice()
              .sort((a, b) => a.position - b.position)
              .map((section) => (
                <Link
                  key={section.id}
                  href={`/sections/${section.slug}/topics` as never}
                  className="block"
                >
                  <Card className="h-full transition-colors hover:bg-accent">
                    <CardHeader>
                      <CardTitle className="text-lg">{section.title}</CardTitle>
                      {section.description && (
                        <CardDescription>{section.description}</CardDescription>
                      )}
                    </CardHeader>
                    <CardContent>
                      <span className="text-sm text-muted-foreground">
                        /{section.slug}
                      </span>
                    </CardContent>
                  </Card>
                </Link>
              ))}
          </div>
        )}
      </section>
    </div>
  )
}
