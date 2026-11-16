import type { MetadataRoute } from "next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://noki.click";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    "",
    "/legal/privacy",
    "/legal/terms",
    "/legal/cookies",
    "/legal/subprocessors",
  ].map((path) => ({
    url: `${siteUrl}${path}`,
    changeFrequency: path ? ("yearly" as const) : ("monthly" as const),
    priority: path ? 0.2 : 1,
  }));
}
