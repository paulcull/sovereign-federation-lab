FROM nginx:1.28.0-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=644 infra/lab-config.live.json /etc/nginx/lab-config.json
COPY dist /usr/share/nginx/html
# Source archives may have private umask permissions. Nginx workers must be
# able to traverse/read the public site regardless of the source host's umask.
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 8080
