# ---------- build ----------
# dist/ 만 꺼내서 호스트의 /srv/www 로 옮김 -> runtime 스테이지 없음
FROM node:22-alpine
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# API는 같은 도메인의 /api 로 호출
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY . .
RUN npm run build