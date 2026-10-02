# ==============================================================================
# AtaRehber — React web UI
# Stage 1 builds the static files; stage 2 serves them with nginx, which also forwards /api to the backend,
# so the browser talks to a single origin (refresh token cookie, no CORS).
# ==============================================================================
FROM node:22-alpine AS build

WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
