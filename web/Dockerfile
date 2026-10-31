FROM nginx:1.28-alpine
COPY nginx.conf.template /etc/nginx/okam.conf.template
COPY entrypoint.sh /entrypoint.sh
COPY index.html app.js controls.js exports.js archive.js styles.css /usr/share/nginx/html/
USER 101:101
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
