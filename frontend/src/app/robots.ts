import type { MetadataRoute } from "next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://noki.click";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/app",
        "/api",
        "/media",
        "/invite",
        "/login",
        "/register",
        "/reset-password",
        "/forgot-password",
        "/verify-email",
      ],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
