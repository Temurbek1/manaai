# Scoped production MANA AI Swagger

Status: published and verified on 2026-10-13 without an application restart.

The public URL is `https://ai.360rec.uz/docs`. It exposes only the eleven product
inference contracts and their capability index. Internal operational endpoints,
authentication/user management and the separate 360REC audio contract are not
published in this schema. Business requests still require the existing
`APP_API_KEY` Bearer token; no token is embedded in documentation.

## Export and deployment

Run `scripts/export_mana_ai_docs.py` using the exact running product API image's
router and dependency versions. The exporter builds only an isolated schema
container: it never invokes an application factory/lifespan or reads settings,
data sources, OpenAI or a database. Record the immutable runtime image identifier
in its manifest; refuse reuse of the artifact output directory.

Self-host the pinned `swagger-ui-dist` 5.33.2 bundle and CSS. Verify the official
npm tarball's SHA-512 integrity before extracting those two files. The runtime
does not load scripts from a third-party CDN or send schemas to an online
validator. Authorization persistence and automatic Try it out are disabled.
HTML and scripts explicitly use UTF-8; versioned asset queries avoid previously
cached missing-charset headers at the edge. Preserve bundled license notices.
An explicitly executed POST still invokes paid inference; browsing docs does not.

Publish to a new versioned `/var/www/mana-ai-docs/` directory, set its `current`
symlink, and include `deploy/nginx/mana-ai-docs.conf` only inside the existing
`ai.360rec.uz` TLS server. Back up the actual server configuration first; preserve
the existing proxy destinations, TLS and Cloudflare origin restrictions.
Test `nginx -t` before a graceful reload. Do not change `APP_ENV`, production
credentials, SSH, schedulers or application containers to publish documentation.

Verify public HTML, JSON, local asset MIME types, all twelve endpoint paths and
Bearer-based authentication. Test only the non-inference capability GET; never run a
paid analysis as an implicit docs smoke test. Check the rendered browser and
that main/audio and UI containers have not restarted.

After any product API deployment, regenerate from its new immutable image and
verify the complete path/schema contract before switching artifacts. This
export is release-bound, not a continuously introspected schema. Rollback removes
only the new ingress include or restores the prior artifact symlink, followed by
`nginx -t` and a graceful reload; no database restore is needed.

Implementation follows FastAPI's
[custom Swagger assets](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/)
and Nginx's [exact locations and alias](https://nginx.org/en/docs/http/ngx_http_core_module.html#alias).

## Deployed evidence

- Product runtime: unchanged `mana-ai-backend:e73c10a`, immutable image
  `sha256:f73523721727298e7a3876a8c7236d28644b949df4ecde8eef667ce69fba97c1`.
  Its router/dependencies generated the schema in a networkless, read-only
  container without deployment credentials or application startup.
- Artifact: `/var/www/mana-ai-docs/b81f458-e73c10a-assets`; `current` points here.
  Schema SHA-256 `d86d81561b436fa3819163292b947b6a509bdb351eb290d5498937c730568b10`;
  HTML SHA-256 `73e64d4429cbc2f4042bf1b32c444589aa2459ed0bae6bd2993ba66846c7fae7`.
- Pinned official npm tarball SHA-512 verified before use. Bundle SHA-256
  `6b3bfcaff3fc82c0e6992ca4b370c4f22970dec35fff60d229302b3ee7688715`,
  CSS `1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321`.
- The only original Nginx server-file edit adds the docs snippet include. Proxy,
  origin restrictions and TLS are byte-for-byte preserved. `nginx -t` passed
  before graceful reload. Original server configuration is protected in
  `/var/backups/mana-ai/inference-docs-b81f458/files/etc/nginx/sites-enabled/ai.360rec.uz.conf`.
- Public HTML, schema, JS, CSS and health GETs return 200. Capability GET without
  a token returns 401; the unchanged existing token returns all eleven capabilities.
- A clean isolated browser renders the document and the authorization dialog,
  loads all twelve contracts, and reports zero page errors. Expansion shows eleven
  POSTs and one GET. No inference POST, source read or browser credential storage
  was used for acceptance. The initial missing-charset rendering error was corrected
  and independently retested; HTTP 200 alone was not considered success.
- Main/audio, UI, scheduler and PostgreSQL containers were not recreated.
  Existing credentials and SSH configuration retained their fingerprints.

Ignored acceptance evidence: `output/docs-release-20261013/`, including browser
screenshots, public headers, minimized authenticated GET results and protected
configuration comparisons. Application `/redoc` and operational Swagger remain disabled.
