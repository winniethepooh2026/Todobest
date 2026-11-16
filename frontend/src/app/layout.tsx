import type { Metadata } from "next";

import { CookieConsent } from "@/components/analytics/cookie-consent";
import { Providers } from "@/components/providers/providers";
import { ThemeScript } from "@/components/theme-script";

import "./globals.css";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://noki.click";

export const metadata: Metadata = {
  title: {
    default: "Noki — задачи и знания команды в одном месте",
    template: "%s · Noki",
  },
  description:
    "Noki объединяет задачи, канбан-доски и документы, чтобы команда работала без хаоса и лишних переключений.",
  metadataBase: new URL(siteUrl),
  openGraph: {
    title: "Noki — работайте вместе без рабочего хаоса",
    description:
      "Задачи, доски и документы команды в одном понятном пространстве.",
    url: siteUrl,
    siteName: "Noki",
    locale: "ru_RU",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Noki — задачи и знания команды в одном месте",
    description: "Работайте вместе без рабочего хаоса.",
  },
  icons: [{ rel: "icon", url: "/noki-mark.svg" }],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <head>
        <ThemeScript />
      </head>
      <body>
        <Providers>{children}</Providers>
        <CookieConsent />
      </body>
    </html>
  );
}
