# syntax=docker/dockerfile:1.7

# --- Stage 1: deps -----------------------------------------------------------
FROM node:20-alpine AS deps

# pnpm via corepack (pinned by packageManager in package.json).
RUN corepack enable

WORKDIR /app

# Copy manifests first for cache reuse.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- Stage 2: builder --------------------------------------------------------
FROM node:20-alpine AS builder

RUN corepack enable

WORKDIR /app

# Reuse installed node_modules.
COPY --from=deps /app/node_modules ./node_modules

# Copy the rest of the frontend source.
COPY frontend/ ./

# API URL baked into the static bundle. Browser hits this; in docker-compose
# the browser still runs on the host machine so localhost:8000 is correct.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# --- Stage 3: runtime --------------------------------------------------------
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user (uid 1001 — node images already define `node` at 1000; keep
# a dedicated app user for clarity).
RUN addgroup --system --gid 1001 nextjs \
 && adduser  --system --uid 1001 --ingroup nextjs nextjs

# Copy the standalone output + static assets + public/.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
