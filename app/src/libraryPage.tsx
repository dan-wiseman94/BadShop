import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { rpc } from './rpc';
import { useUI } from './store';

const PAGE_SIZE = 50;

export function useLibraryPage(query = '', tags: string[] = []) {
  const ready = useUI(state => state.status === 'ready');
  const key = JSON.stringify([query, tags]);
  const [position, setPosition] = useState({ key, offset: 0 });
  const offset = position.key === key ? position.offset : 0;
  const result = useQuery({
    queryKey: ['library.page', query, tags, offset],
    queryFn: () => rpc.request('library.page', { query, tags, offset, limit: PAGE_SIZE }),
    enabled: ready, gcTime: 0,
  });
  const total = result.data?.total ?? 0;
  const controls = <nav aria-label="Saved material pages" style={{ gridColumn: '1 / -1' }}>
    {result.error && <p role="alert">{result.error.message}</p>}
    {(total > PAGE_SIZE || offset > 0) && <>
      <button type="button" disabled={offset === 0 || result.isFetching}
        onClick={() => setPosition({ key, offset: Math.max(0, offset - PAGE_SIZE) })}>Previous materials</button>
      <span> {Math.min(offset + 1, total)}–{Math.min(offset + PAGE_SIZE, total)} of {total} </span>
      <button type="button" disabled={offset + PAGE_SIZE >= total || result.isFetching}
        onClick={() => setPosition({ key, offset: offset + PAGE_SIZE })}>Next materials</button>
    </>}
  </nav>;
  return { entries: result.data?.entries ?? [], collections: result.data?.collections ?? [], controls };
}
