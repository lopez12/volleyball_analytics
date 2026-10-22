# Architect Brief - Deploy Hardening: Generated 404, robots.txt, sitemap.xml, and a YouTube/Chart.js-aware CSP via `_headers`

Date: 2026-10-21

## Objective

Teach `generate.py` to emit four deploy artifacts into `docs/` - a themed `404.html`, `robots.txt`, `sitemap.xml`, and a Cloudflare Pages `_headers` file carrying security headers plus a Content-Security-Policy that allows the site's existing YouTube and Chart.js usage - so the live site on `volleyballanalytics.app` is crawlable, has a branded not-found page, and ships hardened response headers, with zero new runtime dependencies and no change to any existing page.

## Scope

Modified (committed source):
- `renderer.py`: add one new pure-HTML renderer, `render_not_found_page(today)`. No file I/O, no SQLite.
- `generate.py`: add a `SITE_URL` constant (env-overridable); in `main()`, after all pages and the root index are written, emit `docs/404.html`, `docs/robots.txt`, `docs/sitemap.xml`, and `docs/_headers`; add a private `_build_sitemap(...)` helper. All file I/O stays here.

Generated (never hand-edited, produced by the above):
- `docs/404.html`, `docs/robots.txt`, `docs/sitemap.xml`, `docs/_headers`.

Untouched: `analytics.py`, `db.py`, `validate_logs.py`, `export_csv.py`, `styles.css`, `teams/**`, `logger/**`, every existing renderer and page, the SQLite schema, and both CI workflows.

## Requirements

1. **`SITE_URL` constant.** `generate.py` defines `SITE_URL`, read from the environment with a default:
   - `SITE_URL = os.environ.get('SITE_URL', 'https://volleyballanalytics.app').strip().rstrip('/')`.
   - It is the canonical origin (scheme + host, no trailing slash) used to build absolute URLs in `robots.txt` and `sitemap.xml`. Nothing else depends on it.

2. **Generated `404.html`.** `render_not_found_page(today)` in `renderer.py` returns a full HTML document, written by `generate.py` to `docs/404.html`:
   - Spanish copy: a heading like `Página no encontrada`, a short sentence, and a link back to home.
   - Reuses the shared theme/dark-mode boot snippet and favicon exactly like the other pages, so there is no light/dark flash and the toggle works.
   - **Root-absolute asset and link paths only** (`/styles.css`, `/favicon.ico`, home link `/`), never relative - a 404 is served for URLs at any depth, so relative paths would break. This is the one structural difference from the existing depth-2 pages.
   - All dynamic strings pass through `html.escape`.

3. **Generated `robots.txt`.** `generate.py` writes `docs/robots.txt` with exactly:
   ```
   User-agent: *
   Allow: /
   Sitemap: {SITE_URL}/sitemap.xml
   ```
   (trailing newline, `{SITE_URL}` interpolated).

4. **Generated `sitemap.xml`.** After all HTML is written, `_build_sitemap(...)` walks `docs/` for `*.html` files and emits a valid `urlset` to `docs/sitemap.xml`:
   - One `<url>` per `.html` file, `<loc>` = `SITE_URL` + '/' + the file's POSIX path relative to `docs/`.
   - **Exclude `404.html`** (an error page must not be in the sitemap).
   - `<lastmod>` = the build date in ISO 8601 (`date.today().isoformat()`), the same for every entry.
   - Entries are emitted in a deterministic sorted order, and every `<loc>` value is XML-escaped (stdlib `xml.sax.saxutils.escape`).
   - Standard header: `<?xml version="1.0" encoding="UTF-8"?>` and the `http://www.sitemaps.org/schemas/sitemap/0.9` namespace.

5. **Generated `_headers` (Cloudflare Pages).** `generate.py` writes `docs/_headers` applying to all paths (`/*`) with these response headers:
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
   - `X-Frame-Options: SAMEORIGIN`
   - `Content-Security-Policy:` the single-line policy in Req 6.

6. **CSP that fits the site as it is today.** The policy must not break any current page, the dark-mode inline boot script, Chart.js, or the logger's YouTube playback. Ship this starting policy:
   ```
   default-src 'self';
   script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://www.youtube.com https://s.ytimg.com;
   style-src 'self' 'unsafe-inline';
   img-src 'self' data: https://i.ytimg.com;
   frame-src https://www.youtube.com https://www.youtube-nocookie.com;
   connect-src 'self' https://www.youtube.com;
   font-src 'self';
   object-src 'none';
   base-uri 'self';
   frame-ancestors 'self'
   ```
   - `'unsafe-inline'` in `script-src`/`style-src` is accepted **for now** because the dashboards use inline boot/collapsible scripts and inline styles; tightening to hashes/nonces is explicitly a later brief (see Out of Scope).
   - The developer must **verify on a Cloudflare preview deployment** before this reaches production that: every dashboard page renders styled, Chart.js charts draw, the dark-mode toggle and collapsibles work, and the logger loads and plays a YouTube segment. If any of those breaks, adjust only the specific directive that caused it and note the change in the PR.

7. **Backward compatibility.** `_headers` is a Cloudflare Pages convention; GitHub Pages and `file://` ignore it harmlessly. `robots.txt`/`sitemap.xml`/`404.html` are additive. No existing page's bytes change except the unrelated build-date string. Old match logs build unchanged.

## Constraints

- **Module layering.** HTML lives in `renderer.py` (`render_not_found_page`); all file writing and the filesystem walk live in `generate.py`. `renderer.py` does no I/O; `generate.py` holds no HTML templates beyond calling the renderer.
- **Standard library only.** Use `pathlib`/`os`, `datetime.date`, `html.escape`, and `xml.sax.saxutils.escape`. No new runtime dependency, no new third-party package, no build step.
- **Source vs. generated.** The four artifacts are produced by `generate.py` on every build. They are never hand-created in `docs/`. `docs/` stays gitignored.
- **Deterministic build.** Re-running `python generate.py` on the same day produces byte-identical `404.html`, `robots.txt`, `sitemap.xml`, and `_headers`. Ordering (sitemap entries, header lines) is fixed, not filesystem-order dependent.
- **Escape everything data-derived.** Any interpolated string that reaches HTML/XML is escaped.
- **`SITE_URL` is the only origin literal.** Do not hard-code `volleyballanalytics.app` anywhere else; build every absolute URL from `SITE_URL`.

## Decisions (do not re-decide)

- **`_headers` over dashboard Transform Rules for response headers.** Putting the security headers and CSP in a generated `_headers` keeps them versioned in source and reviewable, and makes the CSP evolve alongside the code that needs it. Response-header Transform Rules in the Cloudflare dashboard are therefore **not** used - to avoid two competing sources of the same headers. (Network/platform toggles - HTTPS, HTTP/3, HSTS, redirects, analytics - stay in the dashboard; those are not response headers and do not conflict.)
- **CSP keeps `'unsafe-inline'` for now.** The site relies on inline scripts (theme boot, collapsibles) and inline styles. A nonce/hash rollout is real work and risks breaking pages; it is deferred to its own brief rather than rushed here.
- **Sitemap lists actual `.html` paths.** Pretty/trailing-slash canonicalization (mapping `index.html` to its directory URL) is deferred; listing real file paths is correct, complete, and deterministic.
- **404 uses root-absolute paths.** Because Cloudflare serves `/404.html` for a miss at any URL depth, its CSS/favicon/home references must be absolute from the root, unlike the existing depth-relative pages.
- **www to apex (or apex to www) redirect stays in the dashboard.** It is a routing concern, handled by a Cloudflare Redirect Rule, not by this build. (Out of scope here.)
- **Archive.** The prior in-flight brief (ruff lint + CI tuning) has shipped (`ruff.toml` and `.pre-commit-config.yaml` exist and `generate.py` guards `webbrowser.open` with `CI`) and is archived as `briefs/BRIEF-10-ruff-lint-ci-workflow.md`. This brief becomes BRIEF-11 once it ships.

## Out of Scope

- The **dashboard-only Cloudflare settings** (Always Use HTTPS, HTTP/3, HSTS, minimum TLS, Early Hints, Web Analytics, www/apex redirect, Bot Fight Mode, protecting preview deployments with Access). Those are ops configuration, not repo changes, and are given to the owner as steps in chat.
- **Tightening the CSP** to nonces/hashes and removing `'unsafe-inline'`. A separate future brief.
- A **custom Cloudflare Web Analytics `<script>`** injected into pages. If wanted later, that is a renderer change under its own brief; the no-code automatic mode needs nothing here.
- Changing existing pages' relative asset paths, the SQLite schema, the match-log grammar, `validate_logs.py`, or either CI workflow.
- Downloading, hosting, or proxying YouTube; any payment/entitlement work.

## Acceptance Criteria

1. `python generate.py` writes `docs/404.html`, `docs/robots.txt`, `docs/sitemap.xml`, and `docs/_headers`, and still opens the browser locally / stays silent under `CI`. (Req 1-5)
2. `docs/404.html` is a themed Spanish not-found page whose `styles.css`, `favicon.ico`, and home link are **root-absolute**, with a working dark-mode boot (no flash). (Req 2)
3. `docs/robots.txt` matches Req 3 exactly, with `Sitemap:` built from `SITE_URL`. Setting `SITE_URL=https://example.test python generate.py` changes the sitemap host accordingly. (Req 1, 3)
4. `docs/sitemap.xml` is well-formed XML, contains one `<url>` per generated `.html` except `404.html`, every `<loc>` starts with `SITE_URL`, `<lastmod>` is today's ISO date, and the output is identical across two same-day runs. (Req 4, Constraints)
5. `docs/_headers` applies the five headers at `/*`, and the CSP string matches Req 6. (Req 5, 6)
6. On a Cloudflare **preview** deployment: all dashboards render styled, Chart.js draws, dark-mode toggle and collapsibles work, and the logger plays a YouTube segment - with no CSP violation in the browser console. Any directive adjusted to achieve this is noted in the PR. (Req 6)
7. HTML/XML from data-derived strings is escaped; `SITE_URL` is the only origin literal in the tree. (Constraints)
8. No existing page changes except the build-date string; `python validate_logs.py` output is unchanged; no new dependency is imported. (Req 7, Constraints)

## References

- Orchestrator entry point and where to emit the artifacts: [generate.py](generate.py) `main()` (after the root index is written, near the end).
- Existing favicon copy and `DOCS_ROOT`: [generate.py](generate.py#L55-L57), [generate.py](generate.py#L320-L321).
- Renderers and shared head/theme snippets (model `render_not_found_page` on these): [renderer.py](renderer.py).
- Chart.js CDN usage the CSP must allow: [renderer.py](renderer.py#L1097).
- `docs/` is gitignored (artifacts are build output): [.gitignore](.gitignore).
- Cloudflare deploy context: build command `python generate.py`, output dir `docs`, `PYTHON_VERSION=3.12`.
- Archived prior brief: [briefs/BRIEF-10-ruff-lint-ci-workflow.md](briefs/BRIEF-10-ruff-lint-ci-workflow.md).
