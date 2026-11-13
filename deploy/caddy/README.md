# Sandbox reverse proxy (Caddy)

This proxy gives every E2B sandbox a stable, branded URL. Clients (the dashboard
and the SDKs) only ever see `https://{sandbox_id}.run.midsphere.com`; the
ephemeral `8000-{sandbox_id}.e2b.app` host stays internal.

```
client ── https://{sandbox_id}.run.midsphere.com ──▶ Caddy ──▶ https://8000-{sandbox_id}.e2b.app
```

The backend mints the public URL in `apps/runs/api/types.py`
(`https://{run.sandbox_id}.{runtime.sandbox_domain}`) and the `agent_server`
inside each sandbox listens on port 8000. Caddy captures the sandbox id from the
subdomain and rewrites the request to the E2B edge, terminating TLS with a
wildcard certificate.

## Why a standalone droplet, not App Platform

This component is **not** in `deploy/digitalocean/app.yaml`. App Platform can't:

- route a wildcard subdomain (`*.run.midsphere.com`) to a single component and
  derive the upstream host per-request from the subdomain,
- run a custom Caddy build with a DNS-provider plugin, or
- persist the ACME account/cert store across deploys for DNS-01 wildcard issuance.

Run it as a small standalone droplet (or any Docker host) instead.

## DNS configuration (Cloudflare)

1. **Wildcard record.** Add a record for `*.run.midsphere.com` pointing at the
   Caddy host:
   - **A** record → the droplet's public IPv4 (recommended), or
   - **CNAME** → a hostname that resolves to the droplet.
2. **Proxy status: DNS only (grey cloud).** Turn Cloudflare's orange-cloud proxy
   **off** for the wildcard. Caddy terminates TLS itself, and Cloudflare's proxy
   would otherwise buffer responses and cap idle time — both fatal to the
   long-lived SSE/WebSocket streams sandboxes use.
3. **API token for DNS-01.** Create a Cloudflare API token scoped to the
   `run.midsphere.com` zone with **Zone → DNS → Edit** (and **Zone → Zone →
   Read**). Caddy uses it to solve the DNS-01 challenge for the wildcard cert.
   Wildcard certificates cannot be issued via HTTP-01.

## Environment

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | yes | — | DNS-01 challenge for wildcard TLS |
| `SANDBOX_DOMAIN` | no | `run.midsphere.com` | Apex of the wildcard; must match the backend's `SANDBOX_DOMAIN` |
| `ACME_EMAIL` | yes | — | Let's Encrypt expiry/contact address |

`SANDBOX_DOMAIN` here and on the backend (`config/runtime.py` →
`runtime.sandbox_domain`) must be identical, or clients will be handed URLs this
proxy doesn't serve.

## Build & run

```bash
docker build -t midsphere-caddy deploy/caddy

docker run -d --name midsphere-caddy --restart unless-stopped \
  -p 80:80 -p 443:443 -p 443:443/udp \
  -e CLOUDFLARE_API_TOKEN=cf_xxx \
  -e SANDBOX_DOMAIN=run.midsphere.com \
  -e ACME_EMAIL=ops@midsphere.com \
  -v caddy_data:/data \
  -v caddy_config:/config \
  midsphere-caddy
```

The `caddy_data` volume holds the ACME account and issued certificates — keep it
persistent so the wildcard isn't re-issued (and rate-limited) on every restart.
Port `443/udp` enables HTTP/3.

## How the rewrite works

The `Dockerfile` builds Caddy with `github.com/caddy-dns/cloudflare` (the stock
image ships no DNS plugins). The `Caddyfile`:

- serves `*.{$SANDBOX_DOMAIN}` and gets a wildcard cert via the Cloudflare
  DNS-01 challenge,
- captures the sandbox id from the leftmost label with
  `header_regexp sandbox Host ^([a-z0-9]+)\.` (Caddy's `*` matches a single
  label, so the rest of the host is already the configured domain),
- reverse-proxies to `https://8000-{re.sandbox.1}.e2b.app`, rewriting the `Host`
  header to the E2B host (E2B routes by Host/SNI),
- sets `flush_interval -1` so streamed responses aren't buffered; WebSocket
  upgrades are detected and streamed automatically, and Caddy strips hop-by-hop
  headers per the HTTP spec on its own.

Requests on the wildcard that don't look like a sandbox host return a plain 404.
