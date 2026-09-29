FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY quasar.config.ts index.html tsconfig.json postcss.config.js ./
COPY src ./src
RUN npm ci && npx quasar build

FROM nginx:1.27-alpine
COPY --from=build /app/dist/spa /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
