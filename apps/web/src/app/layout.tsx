import type { ReactNode } from "react";

import "./globals.css";

/**
 * The locale layout owns <html lang>, so this root only exists to satisfy
 * Next's requirement for a root layout above the [locale] segment.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
