# ---- Build Stage ----
FROM node:18-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps

COPY . .
ARG REACT_APP_API_URL=/api
ENV REACT_APP_API_URL=$REACT_APP_API_URL

RUN npm run build

# ---- Runtime Stage ----
FROM nginx:alpine

RUN apk update && apk upgrade --no-cache

WORKDIR /usr/share/nginx/html

RUN rm -rf ./*

COPY --from=build /app/build .
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]