import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { queries, useArtifact } from '../src/data';
import { rpc } from '../src/rpc';
import { useUI } from '../src/store';
import type { Artifact } from '../src/types';
import type { BinaryArtifact } from '../src/mediaWire';

afterEach(() => {
  queries.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  queries.setDefaultOptions({ queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30000 } });
});

it('accounts concurrent media completions before admitting more bytes and releases view URLs', async () => {
  queries.clear();
  queries.setDefaultOptions({ queries: { retry: false } });
  useUI.getState().set({ status: 'ready' });
  const created = vi.fn(() => 'blob:owned');
  const revoked = vi.fn();
  vi.stubGlobal('URL', { createObjectURL: created, revokeObjectURL: revoked });
  // This isolates admission accounting. Transport byte-length validation has its
  // own binary-frame tests; allocating 150 MiB is unnecessary for this race.
  vi.spyOn(rpc, 'media').mockImplementation(async (_method, { id }) => ({
    meta: { id } as Artifact, mime: 'image/png', blob: new Blob(['x']), byteLength: 50 * 2 ** 20,
  }));
  const hook = renderHook(() => [useArtifact('one'), useArtifact('two'), useArtifact('three')], {
    wrapper: ({ children }) => <QueryClientProvider client={queries}>{children}</QueryClientProvider>,
  });
  await waitFor(() => expect(hook.result.current.filter(query => query.isError)).toHaveLength(1));
  expect(hook.result.current.filter(query => query.isSuccess)).toHaveLength(2);
  const retained = queries.getQueryCache().findAll({ queryKey: ['artifact'] })
    .reduce((sum, query) => sum + ((query.state.data as BinaryArtifact | undefined)?.byteLength ?? 0), 0);
  expect(retained).toBe(100 * 2 ** 20);
  await waitFor(() => expect(created).toHaveBeenCalledTimes(2));
  hook.unmount();
  expect(revoked).toHaveBeenCalledTimes(2);
});
