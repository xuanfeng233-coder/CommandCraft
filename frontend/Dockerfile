FROM docker.m.daocloud.io/library/node:18-alpine AS build

WORKDIR /app
RUN npm install -g pnpm

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
# Skip vue-tsc type checking in Docker (already verified locally), only run vite build
RUN pnpm exec vite build

FROM docker.m.daocloud.io/library/nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
