import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

/**
 * Locale negotiation and prefixing. Next 16 renamed this file convention from
 * `middleware` to `proxy`; next-intl's handler is unchanged.
 */
export default createMiddleware(routing);

export const config = {
  // Every path except Next internals and files with an extension.
  matcher: "/((?!api|_next|_vercel|.*\\..*).*)",
};
