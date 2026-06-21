import { create } from 'zustand';

/**
 * Global UI session state: which WITSML server and well are currently
 * selected. Kept deliberately small; server data lives in React Query.
 */
interface SessionState {
  selectedServerId: string | null;
  selectedWellUid: string | null;
  setSelectedServer: (serverId: string | null) => void;
  setSelectedWell: (wellUid: string | null) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  selectedServerId: null,
  selectedWellUid: null,
  setSelectedServer: (selectedServerId) => set({ selectedServerId }),
  setSelectedWell: (selectedWellUid) => set({ selectedWellUid }),
}));
