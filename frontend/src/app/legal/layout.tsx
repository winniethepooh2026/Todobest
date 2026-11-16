import Link from "next/link";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto min-h-screen max-w-3xl px-6 py-12"><Link href="/" className="font-semibold">Noki</Link><nav className="mt-6 flex flex-wrap gap-4 text-sm text-muted-foreground"><Link href="/legal/terms">Условия</Link><Link href="/legal/privacy">Конфиденциальность</Link><Link href="/legal/cookies">Cookies</Link><Link href="/legal/subprocessors">Субпроцессоры</Link></nav><article className="prose prose-neutral mt-10 max-w-none dark:prose-invert">{children}</article></main>;
}
