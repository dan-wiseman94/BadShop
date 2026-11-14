import { create } from 'zustand';
import type { DocumentContext } from './wire.generated';

/** Live presentation only. Completed messages and approvals stay in the document cache. */
export const useStream = create<{ text: string; context?: DocumentContext }>(() => ({ text: '' }));
