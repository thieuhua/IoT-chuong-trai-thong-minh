# React build served by nginx, which also proxies the API to the backend container.
# Built and started by deployment/compose.yaml (profile "app").
FROM node:20-alpine AS build
WORKDIR /src
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
