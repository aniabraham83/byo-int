# Build stage
# Pinned to a release with the Brotli fix for CVE-2026-111497 (Node2Shell); keep at 24.22.1 or newer.
FROM node:24.22.1-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm cache clean --force \
	&& npm config set registry https://registry.npmjs.org/ \
	&& npm config set fetch-retries 6 \
	&& npm config set fetch-retry-factor 2 \
	&& npm config set fetch-retry-mintimeout 20000 \
	&& npm config set fetch-retry-maxtimeout 120000 \
	&& sh -c 'for i in 1 2 3; do npm ci --no-audit --no-fund --cache /tmp/.npm --prefer-online && exit 0; echo "npm ci attempt $i failed, retrying..."; npm cache clean --force; done; exit 1' \
	&& npm cache clean --force
COPY . .
RUN npm run build

# Serve stage
# Pinned to a release with the nginx2root fixes (CVE-2026-123007 and others, fixed in
# 1.30.7 / 1.31.9); keep at 1.31.9 or newer.
FROM nginx:1.31.10-alpine
RUN apk add --no-cache openssl \
	&& mkdir -p /etc/nginx/certs \
	&& mkdir -p /var/cache/nginx/client_temp \
	&& mkdir -p /var/cache/nginx/proxy_temp \
	&& mkdir -p /var/cache/nginx/fastcgi_temp \
	&& mkdir -p /var/cache/nginx/uwsgi_temp \
	&& mkdir -p /var/cache/nginx/scgi_temp \
	&& mkdir -p /var/run/nginx \
	&& openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
	   -subj "/C=US/ST=Local/L=Local/O=BYO-INT/CN=localhost" \
	   -keyout /etc/nginx/certs/localhost.key \
	   -out /etc/nginx/certs/localhost.crt
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
RUN sed -i '/^user\s\+/d; s|^pid\s\+[^;]*;|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf
RUN chown -R nginx:nginx /usr/share/nginx/html /etc/nginx /var/cache/nginx /var/run/nginx
RUN grep -q '^nginx:' /etc/group || addgroup -g 101 -S nginx
RUN grep -q '^nginx:' /etc/passwd || adduser -S -D -H -u 101 -h /var/cache/nginx -s /sbin/nologin -G nginx -g nginx nginx
USER nginx
EXPOSE 8080 8443
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget --no-verbose --tries=1 --spider --no-check-certificate https://127.0.0.1:8443/ || exit 1
CMD ["/docker-entrypoint.sh"]
