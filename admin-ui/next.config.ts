import type { NextConfig } from "next";

const defaultFastApiBaseUrl = "http://127.0.0.1:8000";
const configuredFastApiBaseUrl =
  process.env.FASTAPI_BASE_URL ?? defaultFastApiBaseUrl;
const fastApiBaseUrl = configuredFastApiBaseUrl.replace(/\/+$/, "");
const parsedFastApiBaseUrl = new URL(fastApiBaseUrl);
const chatBaseUrl = (
  process.env.OPERATION_CHAT_BASE_URL || fastApiBaseUrl
).replace(/\/+$/, "");
const parsedChatBaseUrl = new URL(chatBaseUrl);

if (
  parsedFastApiBaseUrl.protocol !== "http:" &&
  parsedFastApiBaseUrl.protocol !== "https:"
) {
  throw new Error("FASTAPI_BASE_URL must use http or https");
}
if (!["http:", "https:"].includes(parsedChatBaseUrl.protocol)) {
  throw new Error("OPERATION_CHAT_BASE_URL must use http or https");
}

const scriptSource =
  process.env.NODE_ENV === "development"
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'";

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "connect-src 'self'",
  "font-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data:",
  "object-src 'none'",
  scriptSource,
  "style-src 'self' 'unsafe-inline'",
].join("; ");

const nextConfig: NextConfig = {
  experimental: { proxyTimeout: 120_000 },
  agentRules: false,
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/admin/operation/chat/:path*",
        destination: `${chatBaseUrl}/api/v1/admin/operation/chat/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${fastApiBaseUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
