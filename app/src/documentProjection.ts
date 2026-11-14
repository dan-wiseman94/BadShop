import { useMemo } from 'react';
import type { Session } from './types';

/** Derived indexes only. The revisioned core snapshot remains authoritative. */
export function useDocumentProjection(session: Session | undefined) {
  const steps = session?.steps;
  const artifacts = session?.artifacts;
  const stepsById = useMemo(() => new Map(steps?.map(step => [step.id, step])), [steps]);
  const visibleArtifacts = useMemo(() => {
    const values = Object.values(artifacts ?? {});
    const originals = new Set(values.flatMap(artifact => artifact.original_id ? [artifact.original_id] : []));
    return values.filter(artifact => !originals.has(artifact.id));
  }, [artifacts]);
  return { stepsById, visibleArtifacts };
}
