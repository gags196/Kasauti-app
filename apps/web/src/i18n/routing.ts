import { defineRouting } from "next-intl/routing";

/**
 * Hindi and English ship together — always. Hindi is a first-class locale
 * (plan wedge #2), never a translation layer bolted on later, so every route
 * exists in both from day one.
 */
export const routing = defineRouting({
  locales: ["en", "hi"],
  defaultLocale: "en",
});

export type Locale = (typeof routing.locales)[number];
