import { http } from './http';
import { useAuthStore, type AuthUser } from '../store/auth';

/**
 * Authentication API surface.
 *
 * Conforms to the backend auth router (see `app/auth/deps.py`):
 *   POST /api/auth/login   (OAuth2 password form) -> { access_token, token_type }
 *   GET  /api/auth/me      -> current `User`
 *
 * This module also registers — exactly once, at import time — an axios request
 * interceptor on the shared `http` instance that attaches the bearer token from
 * the auth store. We register here (rather than editing `http.ts`) so the HTTP
 * client stays auth-agnostic while every authenticated call still gets the
 * header. Importing this module anywhere (e.g. from `auth.ts` consumers) wires
 * it up.
 */

/* ------------------------------------------------------------------ */
/* Request interceptor (registered once)                              */
/* ------------------------------------------------------------------ */

let interceptorRegistered = false;

function registerAuthInterceptor(): void {
  if (interceptorRegistered) return;
  interceptorRegistered = true;
  http.interceptors.request.use((config) => {
    const token = useAuthStore.getState().token;
    if (token) {
      config.headers = config.headers ?? {};
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });
}

registerAuthInterceptor();

/* ------------------------------------------------------------------ */
/* DTOs                                                               */
/* ------------------------------------------------------------------ */

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

/* ------------------------------------------------------------------ */
/* Operations                                                         */
/* ------------------------------------------------------------------ */

/**
 * Authenticate with username/password. On success the token is stored and the
 * user profile is fetched and stored. The OAuth2 password flow expects a
 * `application/x-www-form-urlencoded` body with `username`/`password` fields.
 */
export async function login(
  username: string,
  password: string,
): Promise<AuthUser | null> {
  const form = new URLSearchParams();
  form.set('username', username);
  form.set('password', password);

  const { data } = await http.post<LoginResponse>('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });

  // Store the token first so the subsequent /me call carries it.
  useAuthStore.getState().setAuth(data.access_token, null);

  const user = await me();
  useAuthStore.getState().setUser(user);
  return user;
}

/** Fetch the current user profile (requires a stored token). */
export async function me(): Promise<AuthUser> {
  const { data } = await http.get<AuthUser>('/auth/me');
  return data;
}

/**
 * Re-hydrate the user profile on app boot if a token is already present.
 * Clears the session on failure (expired/invalid token). Safe to call when no
 * token is stored (resolves to null without a network call).
 */
export async function refreshSession(): Promise<AuthUser | null> {
  const { token } = useAuthStore.getState();
  if (!token) return null;
  try {
    const user = await me();
    useAuthStore.getState().setUser(user);
    return user;
  } catch {
    useAuthStore.getState().clear();
    return null;
  }
}

/** Clear the local auth session. */
export function logout(): void {
  useAuthStore.getState().clear();
}
