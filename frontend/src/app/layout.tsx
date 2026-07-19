import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Toaster } from 'sonner'

import { AuthBootstrap } from '@/components/auth-bootstrap'
import { KirbyAssistant } from '@/components/kirby/kirby-assistant'
import { Footer } from '@/components/layout/footer'
import { Header } from '@/components/layout/header'
import { ThemeProvider } from '@/components/theme-provider'
import { QueryProvider } from '@/lib/query-client'

import './globals.css'

export const metadata: Metadata = {
  title: 'Neuroforum',
  description: 'Форум о нейробиологии и нейровизуализации',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <AuthBootstrap />
            <div className="flex min-h-screen flex-col">
              <Header />
              <main className="container flex-1 py-8">{children}</main>
              <Footer />
            </div>
            <KirbyAssistant />
            <Toaster richColors closeButton position="top-right" />
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
