import { create } from 'zustand';

export interface HAEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

interface HAState {
  entities: Record<string, HAEntityState>;
  setEntityState: (entityId: string, state: HAEntityState) => void;
}

export const useHAStore = create<HAState>()((set) => ({
  entities: {},
  setEntityState: (entityId, state) =>
    set((s) => ({ entities: { ...s.entities, [entityId]: state } })),
}));
