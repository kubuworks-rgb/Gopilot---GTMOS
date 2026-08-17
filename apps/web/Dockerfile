# Build context is the repository root, because the npm workspace lives there.
FROM node:22-slim AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci

FROM node:22-slim AS build
WORKDIR /repo
# Next.js resolves rewrites() during `next build` and serializes the result into
# the standalone bundle, so the proxy target must be supplied at build time. A
# runtime environment variable would be read too late and silently keep the
# localhost default.
ARG API_PROXY_TARGET=http://api:8000
# NEXT_PUBLIC_* values are inlined into the client bundle at build time too.
ARG NEXT_PUBLIC_AUTH_MODE=demo
ARG NEXT_PUBLIC_OIDC_ISSUER=
ARG NEXT_PUBLIC_OIDC_CLIENT_ID=
ARG NEXT_PUBLIC_OIDC_SCOPE="openid profile email"
ENV NEXT_TELEMETRY_DISABLED=1 \
    API_PROXY_TARGET=${API_PROXY_TARGET} \
    NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE} \
    NEXT_PUBLIC_OIDC_ISSUER=${NEXT_PUBLIC_OIDC_ISSUER} \
    NEXT_PUBLIC_OIDC_CLIENT_ID=${NEXT_PUBLIC_OIDC_CLIENT_ID} \
    NEXT_PUBLIC_OIDC_SCOPE=${NEXT_PUBLIC_OIDC_SCOPE}
# npm workspaces hoist every dependency to the root, so there is no
# apps/web/node_modules to copy.
COPY --from=deps /repo/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY apps/web ./apps/web
RUN npm run build --workspace apps/web

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The standalone output already contains the trimmed server and its dependencies.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
# No apps/web/public directory exists; nothing to copy.

RUN useradd --create-home --uid 10001 gopilot && chown -R gopilot:gopilot /app
USER gopilot

EXPOSE 3000
CMD ["node", "apps/web/server.js"]
