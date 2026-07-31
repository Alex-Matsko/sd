# Multi-stage: build the static SPA with Vite, then serve it with a plain
# nginx image - no Node runtime in the final image, just static files.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite bakes VITE_* variables into the JS bundle at build time (the browser,
# not Docker's network, reads this URL) - written to .env.production so
# Vite's own env loading picks it up for `vite build` (mode=production),
# rather than relying on ambient process.env propagation.
ARG VITE_API_BASE_URL=http://localhost:8080
RUN echo "VITE_API_BASE_URL=${VITE_API_BASE_URL}" > .env.production
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
