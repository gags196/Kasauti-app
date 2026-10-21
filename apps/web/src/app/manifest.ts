import type { MetadataRoute } from "next";

/**
 * Installability, the cheap half of the "no mobile app" gap.
 *
 * A manifest makes the app installable from the browser on Android and iOS — a home
 * screen icon and a standalone window — without a native rewrite. It is deliberately
 * *not* accompanied by a service worker: offline caching of a corpus this size is a real
 * design problem (which questions, how stale, what happens to an in-progress paper when
 * the answers cannot be saved), and a half-built offline mode that silently drops a
 * learner's answers would be worse than none.
 *
 * `display: standalone` matters more than it looks for a timed paper: it removes the
 * browser chrome an aspirant would otherwise be tempted to navigate away with.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Kasauti — UPSC Prelims intelligence",
    short_name: "Kasauti",
    description:
      "Every past Prelims question, tagged to the syllabus, in Hindi and English — with what the pattern actually says.",
    start_url: "/",
    display: "standalone",
    // Matches --color-paper in globals.css; a mismatch shows as a flash of the wrong
    // colour on launch.
    background_color: "#fbfaf7",
    theme_color: "#fbfaf7",
    orientation: "portrait-primary",
    categories: ["education"],
    lang: "en",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
    ],
  };
}
