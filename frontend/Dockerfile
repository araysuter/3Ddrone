FROM node:22-alpine AS build-base
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./

FROM build-base AS operator-build
RUN npm run build

FROM build-base AS public-build
ENV VITE_PUBLIC_SHARE_BUILD=true
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS operator-runtime
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=operator-build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD wget -qO- http://127.0.0.1:8080/api/health >/dev/null || exit 1

FROM nginxinc/nginx-unprivileged:1.27-alpine AS public-runtime
COPY frontend/nginx.public.conf /etc/nginx/conf.d/default.conf
COPY --from=public-build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
