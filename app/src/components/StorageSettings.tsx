import { useState } from 'react';
import { rpc } from '../rpc';
import { run, useSession } from '../data';
import type { MethodMap } from '../types';

export function StorageSettings({ onRestore }: { onRestore?: () => void }) {
  const { data: session } = useSession();
  const [report, setReport] = useState<MethodMap['storage.inspect'][1] | null>(null);
  const [busy, setBusy] = useState(false);
  return <section aria-label="Storage and recovery">
    <h3>Storage and recovery</h3>
    <p>Inspect recovery databases, image hashes, unfinished operations, and saved-library entries. Inspection keeps every file unchanged.</p>
    <button disabled={busy} onClick={() => run(async () => {
      setBusy(true);
      try { setReport(await rpc.request('storage.inspect')); } finally { setBusy(false); }
    })}>{busy ? 'Inspecting…' : 'Inspect storage'}</button>
    {report && <div role="status">
      {report.recovery.map(item => <p key={item.file}><strong>{item.file}</strong>: {item.ok ? 'Verified' : 'Needs attention'}.
        {item.pending_operations > 0 && ` ${item.pending_operations} accepted operations have no final receipt; inspect recovered work before repeating them.`}
        {item.error && ` ${item.error}`}</p>)}
      {!report.recovery.length && <p>No retained recovery databases.</p>}
      {report.library.map(item => <p key={item.file}>{item.file}: {item.error}</p>)}
      {!report.library.length && <p>Saved library entries verified.</p>}
    </div>}
    <p>Unreadable library entries stay on disk while healthy entries remain usable. Keep damaged files and rollback copies when seeking repair; never overwrite the only copy.</p>
    {onRestore && session?.restorable && <button disabled={session.turn_running || busy} onClick={onRestore}>Restore previous recovery</button>}
  </section>;
}
