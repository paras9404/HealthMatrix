import { Helmet } from 'react-helmet-async'
import {
  SITE_NAME,
  SITE_URL,
  SITE_LOCALE,
  SITE_LANGUAGE,
  DEFAULT_DESCRIPTION,
  DEFAULT_OG_IMAGE,
  DEFAULT_OG_IMAGE_ALT,
  TWITTER_HANDLE,
  absoluteUrl,
  absoluteImage,
} from '../utils/seo.js'

// Reusable per-page SEO. Everything optional — sensible defaults from utils/seo.js.
//   <Seo
//     title="Page"
//     description="…"
//     path="/browse"
//     image="…"
//     imageAlt="…"
//     jsonLd={[…]}
//     prev="/browse?page=1"
//     next="/browse?page=3"
//     publishedTime={iso}
//     modifiedTime={iso}
//     noindex
//   />
export default function Seo({
  title,
  description = DEFAULT_DESCRIPTION,
  path,
  image,
  imageAlt,
  type = 'website',
  noindex = false,
  jsonLd,
  prev,
  next,
  publishedTime,
  modifiedTime,
  children,
}) {
  const canonical = path ? absoluteUrl(path) : SITE_URL
  const ogImage = absoluteImage(image) || DEFAULT_OG_IMAGE
  const ogImageAlt = imageAlt || DEFAULT_OG_IMAGE_ALT
  const fullTitle = title ? `${title} · ${SITE_NAME}` : `${SITE_NAME} — Compare Supplement Ratings Across Trusted Labs`
  const ldArray = (Array.isArray(jsonLd) ? jsonLd : jsonLd ? [jsonLd] : []).filter(Boolean)

  return (
    <Helmet prioritizeSeoTags>
      <html lang={SITE_LANGUAGE} />
      <title>{fullTitle}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={canonical} />
      {prev && <link rel="prev" href={absoluteUrl(prev)} />}
      {next && <link rel="next" href={absoluteUrl(next)} />}
      {noindex
        ? <meta name="robots" content="noindex, nofollow" />
        : <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />}
      {/* Granular crawler hints — Googlebot honors these per-bot directives */}
      {!noindex && <meta name="googlebot" content="index, follow, max-image-preview:large, max-snippet:-1" />}
      {!noindex && <meta name="bingbot" content="index, follow" />}

      {/* Open Graph */}
      <meta property="og:type" content={type} />
      <meta property="og:site_name" content={SITE_NAME} />
      <meta property="og:title" content={fullTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={canonical} />
      <meta property="og:image" content={ogImage} />
      <meta property="og:image:secure_url" content={ogImage} />
      <meta property="og:image:alt" content={ogImageAlt} />
      <meta property="og:image:width" content="1200" />
      <meta property="og:image:height" content="630" />
      <meta property="og:image:type" content="image/png" />
      <meta property="og:locale" content={SITE_LOCALE} />
      {publishedTime && <meta property="article:published_time" content={publishedTime} />}
      {modifiedTime && <meta property="article:modified_time" content={modifiedTime} />}

      {/* Twitter Card */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:site" content={TWITTER_HANDLE} />
      <meta name="twitter:creator" content={TWITTER_HANDLE} />
      <meta name="twitter:title" content={fullTitle} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={ogImage} />
      <meta name="twitter:image:alt" content={ogImageAlt} />

      {ldArray.map((ld, i) => (
        <script key={i} type="application/ld+json">
          {JSON.stringify(ld)}
        </script>
      ))}

      {children}
    </Helmet>
  )
}
