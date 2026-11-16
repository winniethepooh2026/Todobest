import type { NextConfig } from "next";

const isProduction = process.env.NODE_ENV === "production";

const backendUrl =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8010";

const commonSecurityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
];

// Yandex Metrica (pageview/click tracking + Webvisor session replay) is
// opt-in: the CSP only widens when a counter id is actually configured, so
// anyone who never sets NEXT_PUBLIC_YANDEX_METRIKA_ID keeps the strict
// default policy. Hosts per
// https://yandex.com/support/metrica/en/code/install-counter-csp
const metricaEnabled = Boolean(process.env.NEXT_PUBLIC_YANDEX_METRIKA_ID);
const metricaHosts = ["https://mc.yandex.ru", "https://mc.webvisor.com", "https://mc.webvisor.org"];
const metricaScriptHost = "https://yastatic.net";
const metricaSockets = metricaHosts.map((host) => host.replace("https://", "wss://"));

const productionSecurityHeaders = [
  ...commonSecurityHeaders,
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "base-uri 'self'",
      [
        "connect-src 'self'",
        ...(metricaEnabled ? [...metricaHosts, ...metricaSockets] : []),
      ].join(" "),
      "font-src 'self' data:",
      "form-action 'self'",
      "frame-ancestors 'none'",
      [
        "img-src 'self' blob: data:",
        ...(metricaEnabled ? metricaHosts : []),
      ].join(" "),
      "manifest-src 'self'",
      "object-src 'none'",
      [
        "script-src 'self' 'unsafe-inline'",
        ...(metricaEnabled ? [...metricaHosts, metricaScriptHost] : []),
      ].join(" "),
      "style-src 'self' 'unsafe-inline'",
      "worker-src 'self' blob:",
      "upgrade-insecure-requests",
    ].join("; "),
  },
  ...(process.env.ENABLE_HSTS === "true"
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=31536000",
        },
      ]
    : []),
];

const nextConfig: NextConfig = {
  turbopack: { root: process.cwd() },
  allowedDevOrigins: ["127.0.0.1"],
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: isProduction
          ? productionSecurityHeaders
          : commonSecurityHeaders,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/media/images/:filename*",
        destination: `${backendUrl}/api/v1/uploads/images/:filename*`,
      },
      {
        source: "/media/avatars/:path*",
        destination: `${backendUrl}/api/v1/media/avatars/:path*`,
      },
    ];
  },
};

export default nextConfig;
