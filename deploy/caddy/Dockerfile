# Custom Caddy build for the midsphere sandbox reverse proxy.
#
# The stock caddy image has no DNS provider plugins, and wildcard TLS for
# *.{SANDBOX_DOMAIN} requires the Cloudflare DNS-01 challenge. We build Caddy
# with the caddy-dns/cloudflare module baked in via xcaddy.
#
# Build:
#   docker build -t midsphere-caddy deploy/caddy
#
# Run (see README.md for the full droplet setup):
#   docker run -d --name midsphere-caddy --restart unless-stopped \
#     -p 80:80 -p 443:443 -p 443:443/udp \
#     -e CLOUDFLARE_API_TOKEN=... \
#     -e SANDBOX_DOMAIN=run.midsphere.com \
#     -e ACME_EMAIL=ops@midsphere.com \
#     -v caddy_data:/data -v caddy_config:/config \
#     midsphere-caddy

FROM caddy:2-builder-alpine AS builder
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
