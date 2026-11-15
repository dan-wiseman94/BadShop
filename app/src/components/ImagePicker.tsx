import { FolderOpen } from "lucide-react";
import { action, imageUrl, run, useArtifact, useSession } from "../data";
import { native, pickImages } from "../native";
import type { Artifact } from "../types";

function Thumbnail({ artifact }: { artifact: Artifact }) {
  const { data } = useArtifact(artifact.id, true);
  return <img src={imageUrl(data)} alt="" />;
}
export function ImagePicker({ id, value, onChange, required, disabled, beforeStepIndex }: {
  id: string;
  value?: unknown;
  onChange: (value: string | undefined) => void;
  required?: boolean;
  disabled?: boolean;
  beforeStepIndex?: number;
}) {
  const { data: session } = useSession();
  const selected = session?.artifacts[String(value)];
  const all = Object.values(session?.artifacts ?? {});
  const imports = all.filter((artifact) => artifact.id === selected?.id || !all.some((other) => other.original_id === artifact.id));
  return (
    <div className="image-picker">
      <select
        id={id}
        required={required}
        disabled={disabled}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">Choose an image…</option>
        {!!value && !selected && <option value={String(value)} disabled>Previous image unavailable</option>}
        {imports.map((a) => {
          const producer = session?.steps.find(step => step.id === a.produced_by);
          const tooLate = beforeStepIndex !== undefined && !!producer && producer.index >= beforeStepIndex;
          return <option key={a.id} value={a.id} disabled={tooLate && selected?.id !== a.id}>
            {a.label} ({a.width} × {a.height}){tooLate ? " — Made after this step; choose an imported or earlier picture" : ""}
          </option>;
        })}
      </select>
      {selected && <Thumbnail artifact={selected} />}
      {!!value && !selected && (
        <p className="field-description" role="alert">
          This image is no longer in the session. Choose an available image.
        </p>
      )}
      <button
        type="button"
        title="Open image file"
        disabled={!native || disabled}
        onClick={() =>
          run(async () => {
            const paths = await pickImages();
            if (paths?.length) {
              const result = await action("artifacts.import", {
                path: paths[0],
              });
              onChange(result.working.id);
            }
          })
        }
      >
        <FolderOpen size={15} />
      </button>
    </div>
  );
}
