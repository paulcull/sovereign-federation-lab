# Core HTTP/TLS/static/proxy modules suffice; omit unused image/XML filter dependencies.
FROM nginx:1.30.6-alpine-slim@sha256:3028fc1419f99b95c1c69f844bbaf49dc1b881750c51b497fc721ac4f02a14e6
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=644 infra/lab-config.live.json /etc/nginx/lab-config.json
COPY --chmod=644 infra/lab-config.pilot.json /etc/nginx/lab-config.pilot.json
COPY dist /usr/share/nginx/html
# Source archives may have private umask permissions. Nginx workers must be
# able to traverse/read the public site regardless of the source host's umask.
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 8080
