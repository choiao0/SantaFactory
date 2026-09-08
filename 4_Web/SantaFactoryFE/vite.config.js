import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 서버에서 /api 를 백엔드로 넘긴다. 견적 진행은 SSE 라 스트림이 끊기지 않아야 하는데,
    // http-proxy 는 기본이 스트리밍이고 Spring 은 응답 압축이 기본 off 이므로 추가 설정은 없다.
    // 백엔드가 다른 곳이면 VITE_API_TARGET 으로 바꾼다.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
