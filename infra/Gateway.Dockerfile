FROM nginx:1.30.6-alpine@sha256:ff8328b4279ec385af48cde9ef486e7165ad74b7065cb3cd86c377384e2e2dd5
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=644 infra/lab-config.live.json /etc/nginx/lab-config.json
COPY --chmod=644 infra/lab-config.pilot.json /etc/nginx/lab-config.pilot.json
COPY dist /usr/share/nginx/html
# Source archives may have private umask permissions. Nginx workers must be
# able to traverse/read the public site regardless of the source host's umask.
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 8080
