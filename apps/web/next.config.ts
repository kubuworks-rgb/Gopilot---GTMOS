import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The floating dev badge sits on top of the sidebar footer in `npm run dev`.
  devIndicators: false,
  // Standalone emits a self-contained server bundle so the runtime image needs
  // neither node_modules nor a package install.
  output: "standalone",
  outputFileTracingRoot: __dirname + "/../..",
  async rewrites() {
    const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${target}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
