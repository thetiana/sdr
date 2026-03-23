FROM node:20-alpine AS build
WORKDIR /app
COPY package.json tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src
COPY public ./public
RUN npm install && npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache gettext
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/public/config.template.js /usr/share/nginx/html/config.template.js
EXPOSE 3000
ENTRYPOINT ["/docker-entrypoint.sh"]
