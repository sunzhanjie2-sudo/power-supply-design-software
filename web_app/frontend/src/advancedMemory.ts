import { ref } from 'vue';
import type { Snapshot } from './types';

export interface FrozenDesign { name: string; snapshot: Snapshot; frozenAt: string; caseId: string }
// Memory only: frozen snapshots survive page navigation, not a browser refresh.
export const frozenDesigns = ref<{ a: FrozenDesign | null; b: FrozenDesign | null }>({ a: null, b: null });
