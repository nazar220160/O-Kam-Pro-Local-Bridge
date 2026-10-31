FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.28-alpine AS runtime
COPY nginx.conf.template /etc/nginx/okam.conf.template
COPY entrypoint.sh /entrypoint.sh
COPY --from=build /app/out /usr/share/nginx/html/
COPY --from=build /app/out/csp-script-hashes.txt /etc/nginx/next-csp-script-hashes
USER 101:101
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
