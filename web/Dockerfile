# ABOUTME: Multi-stage Dockerfile for the React web frontend.
# ABOUTME: Build stage uses Node 22; serve stage uses Nginx Alpine for SPA routing.

# Build stage
FROM node:22.9.0-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# VITE_R2_PUBLIC_URL is embedded in the built bundle at compile time.
# Pass --build-arg VITE_R2_PUBLIC_URL=https://... when targeting staging/prod.
ARG VITE_R2_PUBLIC_URL=""
ENV VITE_R2_PUBLIC_URL=$VITE_R2_PUBLIC_URL
RUN npm run build

# Serve stage
FROM nginx:1.27.2-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
