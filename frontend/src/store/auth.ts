import { create } from 'zustand';

/**
 * Authentication session state.
 *
 * Holds the bearer token and the current user profile. The token is persisted
 * to `localStorage` so a page reload stays logged in; the user object is kept
 * in memory and re-fetched via `me()` on boot (see `src/api/auth.ts`).
 *
 * Deliberately framework-light: the axios request interceptor in
 * `src/api/auth.ts` reads `useAuthStore.getState().token` directly, so no React
 * context is required to attach the `Authorization` header.
 */

const TOKEN_KEY = 'witsml.auth.token';

export type AccessLevel = 'normal' | 'admin' | 'super_admin';

export interface AuthUser {
  id: number;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  phone?: string | null;
  address?: string | null;
  position?: string | null;
  access_level: AccessLevel;
  is_active: boolean;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setAuth: (token: string, user: AuthUser | null) => void;
  setUser: (user: AuthUser | null) => void;
  clear: () => void;
  isAdmin: () => boolean;
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage may be unavailable (private mode); fall back to memory only */
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: readStoredToken(),
  user: null,
  setAuth: (token, user) => {
    writeStoredToken(token);
    set({ token, user });
  },
  setUser: (user) => set({ user }),
  clear: () => {
    writeStoredToken(null);
    set({ token: null, user: null });
  },
  isAdmin: () => {
    const lvl = get().user?.access_level;
    return lvl === 'admin' || lvl === 'super_admin';
  },
}));
