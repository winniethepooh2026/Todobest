# ADR 003: Search over encrypted content

## Status

Accepted.

## Context

Task, page, and todo titles remain encrypted with AES-256-GCM. Decrypting every
accessible record to search, sort, or filter does not scale and makes response
time proportional to the total amount of content in a Space.

## Decision

Use an HMAC-SHA256 blind index for exact title matching. Before indexing, a
title is normalized with Unicode NFKC, case folding, whitespace collapsing, and
trimming. The HMAC key is derived from the data-encryption key with domain
separation, and every content kind has a distinct purpose string.

The database stores only the 32-byte blind index alongside the encrypted title.
Task, page, and todo titles are never stored as plaintext. Search first limits
the candidate set by the caller's Team and Space access and then compares the
blind index. Migration `0022` only adds nullable columns. Existing encrypted
rows are authenticated, decrypted, normalized, and indexed afterward by the
resumable `noki backfill-production-data` command in small committed batches.
The bounded, access-controlled lazy path remains as a defensive fallback while
that online backfill is running or for an unexpectedly null index.

Assignee, priority, label, and deadline filters operate on their structured
database fields and do not require title decryption.

## Consequences

- Exact, case-insensitive title search is efficient and preserves the current
  encryption boundary.
- The index reveals equality within one content kind, but not the title itself.
- Prefix, fuzzy, ranking, word-count, and full-text search are intentionally not
  provided by this design.
- If full-text search becomes a product requirement, adopt a separate encrypted
  search service with strict Space-level ACL, deletion propagation, audit logs,
  and an explicit retention policy. Do not silently weaken title encryption.
