# GoliathApp platform UI host — build from repository root:
#   docker build -f apps/platform-host/Dockerfile -t goliath-platform-host:local .
FROM node:22-alpine AS build
WORKDIR /repo
ARG PLATFORM_HOST_REVISION=unknown
ENV PLATFORM_HOST_REVISION=${PLATFORM_HOST_REVISION}
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages packages
COPY apps/platform-host apps/platform-host
RUN npm ci --ignore-scripts
RUN npm run build
RUN npm run build --workspace @goliath/platform-host

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3400
ENV HOSTNAME=0.0.0.0
ARG PLATFORM_HOST_REVISION=unknown
ENV PLATFORM_HOST_REVISION=${PLATFORM_HOST_REVISION}
COPY --from=build /repo/apps/platform-host/.next/standalone ./
COPY --from=build /repo/apps/platform-host/.next/static ./apps/platform-host/.next/static
COPY --from=build /repo/apps/platform-host/public ./apps/platform-host/public
EXPOSE 3400
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:3400/api/health" | grep -q '"status":"ok"' || exit 1
CMD ["node", "apps/platform-host/server.js"]
