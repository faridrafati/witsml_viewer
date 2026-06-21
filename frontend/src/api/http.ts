import axios from 'axios';

/**
 * Shared axios instance. Base URL comes from the Vite env var so the same
 * build can target different backends. No requests are fired at module load.
 */
const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';

export const http = axios.create({
  baseURL,
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * The /health probe lives at the server root (not under /api), so we derive
 * its origin from the API base URL.
 */
export const healthURL = (() => {
  try {
    const url = new URL(baseURL);
    return `${url.origin}/health`;
  } catch {
    return 'http://localhost:8000/health';
  }
})();
