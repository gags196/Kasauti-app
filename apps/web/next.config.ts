import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The repo keeps one curated CLAUDE.md at the root; don't scatter generated
  // agent-instruction files through apps/web on every dev start.
  agentRules: false,
};

export default withNextIntl(nextConfig);
