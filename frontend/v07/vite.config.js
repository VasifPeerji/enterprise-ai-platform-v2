import { defineConfig, loadEnv } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig(({ mode }) => {
  // Load env vars (VITE_TAVILY_API_KEY, VITE_SEARXNG_URL) so the search
  // proxies can be configured per-environment without touching this file.
  // Env file lives at frontend/v07/.env (separate from the backend's root
  // .env) — this keeps server secrets and browser-exposed vars physically
  // distinct, so a typo on the VITE_ prefix can't leak a backend key.
  const env = loadEnv(mode, process.cwd(), '')

  const proxy = {
    '/api/v07': { target: 'http://localhost:8000', changeOrigin: true },
    '/chat': { target: 'http://localhost:8000', changeOrigin: true },
    '/grounded-documents': { target: 'http://localhost:8000', changeOrigin: true },
    // Tavily proxy — required because api.tavily.com doesn't send CORS
    // headers. The path /api/tavily/* is rewritten to api.tavily.com/*.
    '/api/tavily': {
      target: 'https://api.tavily.com',
      changeOrigin: true,
      secure: true,
      rewrite: (path) => path.replace(/^\/api\/tavily/, ''),
    },
  }

  // SearXNG proxy — only registered if the user has configured an instance.
  // Most public instances rate-limit aggressively; self-hosting via Docker
  // (`docker run -p 8888:8080 searxng/searxng`) is the recommended path.
  if (env.VITE_SEARXNG_URL) {
    proxy['/api/searxng'] = {
      target: env.VITE_SEARXNG_URL,
      changeOrigin: true,
      secure: env.VITE_SEARXNG_URL.startsWith('https'),
      rewrite: (path) => path.replace(/^\/api\/searxng/, ''),
    }
  }

  return {
    plugins: [svelte()],
    server: { port: 5173, proxy },
  }
})
