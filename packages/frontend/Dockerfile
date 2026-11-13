# ---------- stage 1: build ----------
FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG PUBLIC_MS_TELEMETRY
ARG PUBLIC_MS_SENTRY_DSN
ARG PUBLIC_MS_POSTHOG_KEY
ARG PUBLIC_MS_POSTHOG_HOST
ARG PUBLIC_MS_API_URL
ARG PUBLIC_ENVIRONMENT
ARG PUBLIC_RELEASE

RUN npm run build

# ---------- stage 2: runtime ----------
FROM node:22-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=4321

USER app

EXPOSE 4321

CMD ["node", "./dist/server/entry.mjs"]
