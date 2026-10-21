import type { Metadata } from "next";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { DemoBanner } from "@/components/demo-banner";
import { SiteHeader } from "@/components/site-header";
import { routing } from "@/i18n/routing";

import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "brand" });
  return {
    title: t("name"),
    description: t("tagline"),
    // Installable from the browser: a home-screen icon and a standalone window, without
    // a native app. See src/app/manifest.ts for why there is no service worker yet.
    manifest: "/manifest.webmanifest",
    icons: { icon: "/icon.svg", apple: "/icon.svg" },
    appleWebApp: { capable: true, title: t("name"), statusBarStyle: "default" },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  return (
    <html lang={locale}>
      <body className="min-h-screen">
        <NextIntlClientProvider>
          <DemoBanner />
          <SiteHeader />
          <main className="mx-auto w-full max-w-5xl px-5 py-10">{children}</main>
          <footer className="mx-auto w-full max-w-5xl px-5 pb-12 pt-4 text-sm text-ink-muted">
            <p>© {new Date().getFullYear()} Kasauti</p>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
