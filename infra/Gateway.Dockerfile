FROM nginx:1.28.0-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/lab-config.live.json /etc/nginx/lab-config.json
COPY dist /usr/share/nginx/html
EXPOSE 8080
