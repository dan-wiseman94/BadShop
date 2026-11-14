"""Local recovery commits. Portable projects remain validated ZIP archives.

The core's document lock owns the single writer. Blobs are published before a
short SQLite transaction, so a failed commit can leave garbage, never references
to partially written bytes. DELETE journaling permits moving the closed database
at startup without losing a WAL. Branch and undo snapshots share hashed nodes.
"""

import contextlib
import hashlib
import json
import os
import secrets
import time
import sqlite3
from pathlib import Path

from badshop.engine.errors import EngineError
from badshop.atomic import sync_directory
from badshop.session.blobs import BlobStore

VERSION = 2
JOURNAL_MODE = 'DELETE'
SYNCHRONOUS = 'EXTRA'
FANOUT = 32
RECEIPT_RESULT_BUDGET = 16 * 2**20
_last_collection = (None, 0.0)


def _encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')


class Nodes:
    def __init__(self, connection):
        self.connection = connection
        self.live = set()
        self.cache = {}

    def node(self, kind, value):
        raw = _encoded([kind, value])
        key = hashlib.sha256(raw).hexdigest()
        if key not in self.live:
            inserted = self.connection.execute('INSERT OR IGNORE INTO nodes VALUES (?, ?)', (key, raw))
            if not inserted.rowcount:
                existing = self.connection.execute('SELECT body FROM nodes WHERE id=?', (key,)).fetchone()
                if existing is None or existing[0] != raw:
                    raise EngineError('recovery metadata failed integrity verification')
            self.live.add(key)
        return key

    def put(self, value):
        if isinstance(value, dict):
            # Keep small operation/message/parameter records together. Splitting
            # every scalar causes thousands of tiny queries during recovery.
            if len(_encoded(value)) <= 4096:
                return self.node('value', value)
            # Preserve insertion order, including the artifact gallery's order.
            return self.node('object', [[key, self.put(item)] for key, item in value.items()])
        if isinstance(value, list):
            children = [self.put(item) for item in value]
            level = [self.node('list', children[i:i + FANOUT]) for i in range(0, len(children), FANOUT)]
            while len(level) > FANOUT:
                level = [self.node('concat', level[i:i + FANOUT]) for i in range(0, len(level), FANOUT)]
            return self.node('concat', level)
        return self.node('value', value)

    def get(self, key, *, depth=0, budget=None):
        if budget is None:
            budget = [0]
        if key in self.cache:
            value, cost = self.cache[key]
            budget[0] += cost
            if budget[0] > 256 * 2**20:
                raise EngineError('recovery metadata is too large')
            return value
        before = budget[0]
        if depth > 128:
            raise EngineError('recovery metadata is too deeply nested')
        row = self.connection.execute('SELECT body FROM nodes WHERE id = ?', (key,)).fetchone()
        if row is None or hashlib.sha256(row[0]).hexdigest() != key:
            raise EngineError('recovery metadata failed integrity verification')
        budget[0] += len(row[0])
        # Includes graph overhead, while the reconstructed document is separately bounded.
        if budget[0] > 256 * 2**20:
            raise EngineError('recovery metadata is too large')
        kind, value = json.loads(row[0])
        def child(ref):
            return self.get(ref, depth=depth + 1, budget=budget)
        if kind == 'value':
            result = value
        elif kind == 'object':
            result = {name: child(ref) for name, ref in value}
        elif kind == 'list':
            result = [child(ref) for ref in value]
        elif kind == 'concat':
            result = [item for ref in value for item in child(ref)]
        else:
            raise EngineError('unknown recovery metadata node')
        self.cache[key] = (result, budget[0] - before)
        return result


def _version(connection, *, create=False, path=None):
    connection.execute('PRAGMA trusted_schema=OFF')
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version == 0 and create:
        connection.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE nodes (id TEXT PRIMARY KEY, body BLOB NOT NULL) WITHOUT ROWID;
            CREATE TABLE head (singleton INTEGER PRIMARY KEY CHECK(singleton=1), root TEXT NOT NULL);
            CREATE TABLE operations (id TEXT PRIMARY KEY, body BLOB NOT NULL) WITHOUT ROWID;
            PRAGMA user_version=2;
            COMMIT;
        ''')
    elif version == 1 and create:
        if path is None:
            raise EngineError('recovery upgrade requires a rollback copy')
        # SQLite backup settles the source and creates an independently readable copy.
        backup = path.with_name(path.stem + '.pre-v2.sqlite')
        staged = backup.with_name('.' + backup.name + '.' + secrets.token_hex(8) + '.part')
        try:
            with contextlib.closing(sqlite3.connect(staged)) as target:
                connection.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise EngineError('recovery rollback copy failed verification')
            with staged.open('rb') as file:
                os.fsync(file.fileno())
            for index in range(1000):
                candidate = backup if index == 0 else backup.with_name(f'{path.stem}.pre-v2.{index}.sqlite')
                try:
                    if os.name == 'nt':
                        os.rename(staged, candidate)
                    else:
                        os.link(staged, candidate)
                    break
                except FileExistsError:
                    continue
            else:
                raise EngineError('too many recovery rollback copies; preserve them before upgrading')
            sync_directory(path.parent)
        finally:
            staged.unlink(missing_ok=True)
        connection.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE operations (id TEXT PRIMARY KEY, body BLOB NOT NULL) WITHOUT ROWID;
            PRAGMA user_version=2;
            COMMIT;
        ''')
    elif version not in (1, VERSION):
        raise EngineError(f'unsupported recovery database version {version}',
                          hint='keep this file and open it with a compatible BadShop version')


def save(session, path: Path, *, operation=None):
    # Import here avoids a second document validation/normalization implementation.
    from badshop.session import project

    session.data.collect_history()
    keep = session.referenced_ids()
    missing = keep - session.artifacts.meta.keys()
    if missing:
        raise EngineError(f'cannot recover missing artifact {min(missing)}')
    if len(keep) + 2 > project.MAX_MEMBERS:
        raise EngineError('cannot save recovery: too many project members')
    payload = session.data.model_dump(mode='json', by_alias=True)
    payload['artifacts'] = {aid: meta.model_dump(mode='json') for aid, meta in session.artifacts.meta.items() if aid in keep}
    raw = _encoded(payload)
    problem = project._size_problem(len(raw), {session.artifacts.meta[aid].blob_id: session.artifacts.size(aid) for aid in keep})
    if problem:
        raise EngineError(f'cannot save recovery: {problem}')
    created_folder = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created_folder:
        sync_directory(path.parent.parent)
    blobs = BlobStore(path.parent / 'blobs')
    # Validate existing content too: never commit a reference to a corrupted blob.
    for aid in keep:
        digest = session.artifacts.meta[aid].blob_id
        target = blobs.path(digest)
        if target.exists():
            blobs.verify(target, digest)
        else:
            blobs.put(session.artifacts.data(aid))
    creating = not path.exists()
    destination = path.with_name(f'.{path.name}.{secrets.token_hex(8)}.part') if creating else path
    try:
        with contextlib.closing(sqlite3.connect(destination)) as connection:
            connection.execute(f'PRAGMA journal_mode={JOURNAL_MODE}')
            connection.execute(f'PRAGMA synchronous={SYNCHRONOUS}')
            _version(connection, create=True, path=path)
            with connection:
                nodes = Nodes(connection)
                root = nodes.put(payload)
                connection.execute('INSERT OR REPLACE INTO head VALUES (1, ?)', (root,))
                if operation is not None:
                    previous = connection.execute('SELECT body FROM operations WHERE id=?', (operation['id'],)).fetchone()
                    if previous and json.loads(previous[0])['fingerprint'] != operation['fingerprint']:
                        raise EngineError('operation identity was reused for another command')
                    connection.execute('INSERT OR REPLACE INTO operations VALUES (?, ?)',
                                       (operation['id'], _encoded(operation)))
                    _trim_receipt_results(connection)
                # A retained branch/undo history is already in the current root.
                # Reclaim old metadata without duplicating complete memberships.
                connection.execute('CREATE TEMP TABLE live (id TEXT PRIMARY KEY) WITHOUT ROWID')
                connection.executemany('INSERT INTO live VALUES (?)', ((key,) for key in nodes.live))
                connection.execute('DELETE FROM nodes WHERE id NOT IN (SELECT id FROM live)')
        if creating:
            os.replace(destination, path)
            sync_directory(path.parent)
    except (sqlite3.Error, OSError) as error:
        raise EngineError('could not commit recovery', hint=str(error)) from None
    finally:
        if creating:
            destination.unlink(missing_ok=True)


def _trim_receipt_results(connection):
    """Bound cached replies while retaining every deduplication identity.

    A compacted committed receipt refuses replay rather than repeating side effects.
    Pending identities and document history are never removed by this cache policy.
    """
    total = connection.execute('SELECT COALESCE(SUM(length(body)), 0) FROM operations').fetchone()[0]
    if total <= RECEIPT_RESULT_BUDGET:
        return
    receipts = [(identity, raw, json.loads(raw))
                for identity, raw in connection.execute('SELECT id, body FROM operations')]
    for identity, raw, receipt in sorted(receipts, key=lambda item: item[2]['created_at']):
        if total <= RECEIPT_RESULT_BUDGET:
            break
        if receipt.get('result') is not None:
            receipt['result'] = None
            compact = _encoded(receipt)
            connection.execute('UPDATE operations SET body=? WHERE id=?', (compact, identity))
            total -= len(raw) - len(compact)


def operation(path: Path, identity: str):
    """Read a receipt without creating files or changing document recovery state."""
    if not path.exists():
        return None
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            _version(connection)
            if connection.execute('PRAGMA user_version').fetchone()[0] == 1:
                return None
            row = connection.execute('SELECT body FROM operations WHERE id=?', (identity,)).fetchone()
            return json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError) as error:
        raise EngineError('operation receipt storage is damaged or unreadable', hint=str(error)) from None


def record_intent(path: Path, receipt: dict):
    """Persist admission against the last committed head without waiting for a worker.

    Cancellation and document replacement must be able to signal a running worker
    while it owns the document lock. This transaction never reads mutable session data.
    """
    try:
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute(f'PRAGMA synchronous={SYNCHRONOUS}')
            _version(connection, create=True, path=path)
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                previous = connection.execute('SELECT body FROM operations WHERE id=?', (receipt['id'],)).fetchone()
                if previous:
                    return json.loads(previous[0])
                connection.execute('INSERT INTO operations VALUES (?, ?)', (receipt['id'], _encoded(receipt)))
    except (sqlite3.Error, OSError) as error:
        raise EngineError('could not record operation intent', hint=str(error)) from None
    return None


def inspect(folder: Path) -> list[dict]:
    """Read-only recovery diagnostics. Never repair in place or discard damaged evidence."""
    reports = []
    for path in sorted(folder.glob('*.sqlite')):
        report = {'file': path.name, 'ok': False, 'version': 0, 'pending_operations': 0, 'error': ''}
        try:
            with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
                _version(connection)
                report['version'] = connection.execute('PRAGMA user_version').fetchone()[0]
                if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise EngineError('database integrity check failed')
                row = connection.execute('SELECT root FROM head WHERE singleton=1').fetchone()
                if row is None:
                    raise EngineError('no committed document')
                payload = Nodes(connection).get(row[0])
                from badshop.session import project
                data = project._session_data(path, _encoded(payload))
                for meta in {meta.blob_id: meta for meta in data.artifacts.values()}.values():
                    BlobStore.verify(folder / 'blobs' / meta.blob_id, meta.blob_id)
                if report['version'] >= 2:
                    report['pending_operations'] = sum(json.loads(row[0]).get('status') == 'pending'
                        for row in connection.execute('SELECT body FROM operations'))
                report['ok'] = True
        except (EngineError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as error:
            report['error'] = str(error)[:500]
        reports.append(report)
    return reports


def collect(folder: Path, *, grace_seconds: float = 86400) -> None:
    """Sweep only old unreferenced blobs under the serialized document lock.

    Both current and previous recovery are roots. Any unreadable database stops
    collection entirely; corruption is never permission to delete evidence.
    """
    from badshop.session.blobs import HASH

    global _last_collection
    previous_folder, previous_time = _last_collection
    if grace_seconds and folder == previous_folder and time.monotonic() - previous_time < 3600:
        return
    live = set()
    try:
        for path in folder.glob('*.sqlite'):
            with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
                _version(connection)
                row = connection.execute('SELECT root FROM head WHERE singleton=1').fetchone()
                if row is None:
                    return
                payload = Nodes(connection).get(row[0])
                live.update(meta.get('blob_id', aid) for aid, meta in payload['artifacts'].items())
    except (EngineError, sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        return
    cutoff = time.time() - grace_seconds
    for path in (folder / 'blobs').iterdir():
        staging = path.name.startswith('.badshop-') and path.name.endswith('.part')
        if (HASH.fullmatch(path.name) or staging) and path.name not in live and not path.is_symlink():
            if path.stat().st_mtime < cutoff:
                path.unlink()
    _last_collection = (folder, time.monotonic())


def settle(path: Path) -> None:
    """Recover a hot rollback journal before moving a database after a crash."""
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True)) as connection:
            _version(connection)
            connection.execute('SELECT root FROM head WHERE singleton=1').fetchone()
    except sqlite3.Error as error:
        raise EngineError('could not settle interrupted recovery', hint=str(error)) from None


def load(path: Path, **session_kw):
    from badshop.session import project
    from badshop.session.artifacts import ArtifactStore

    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            _version(connection)
            row = connection.execute('SELECT root FROM head WHERE singleton=1').fetchone()
            if row is None:
                raise EngineError('recovery has no committed document')
            raw = _encoded(Nodes(connection).get(row[0]))
        if len(raw) > project.MAX_SESSION_BYTES:
            raise EngineError('recovery document is too large')
        data = project._session_data(path, raw)
        if len(data.artifacts) + 2 > project.MAX_MEMBERS:
            raise EngineError('recovery has too many images')
        sizes = {meta.blob_id: (path.parent / 'blobs' / meta.blob_id).stat().st_size for meta in data.artifacts.values()}
        problem = project._size_problem(len(raw), sizes)
        if problem:
            raise EngineError(f'recovery is too large: {problem}')
        artifacts = ArtifactStore(decoder=session_kw.get('decoder'))
        for aid, meta in data.artifacts.items():
            blob_path = path.parent / 'blobs' / meta.blob_id
            if blob_path.stat().st_size > project.MAX_MEMBER_BYTES:
                raise EngineError('recovery image is too large')
            blob = BlobStore.read(blob_path, meta.blob_id)
            artifacts.add(blob, meta.label, produced_by=meta.produced_by, source=meta.source,
                          original_id=meta.original_id, identity=aid,
                          invocation_id=meta.invocation_id, output_key=meta.output_key,
                          input_ids=meta.inputs, legacy_identity=meta.legacy_identity)
        return project._restore(path, data, artifacts, session_kw)
    except (sqlite3.Error, OSError, ValueError, TypeError) as error:
        raise EngineError('recovery is damaged or unreadable', hint=str(error)) from None
