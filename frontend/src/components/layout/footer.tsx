export function Footer() {
  return (
    <footer className="border-t border-border bg-background">
      <div className="container flex h-14 items-center justify-between text-xs text-muted-foreground">
        <span>© {new Date().getFullYear()} Neuroforum</span>
        <span>Форум о нейробиологии и нейровизуализации</span>
      </div>
    </footer>
  )
}
