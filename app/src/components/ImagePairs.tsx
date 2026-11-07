import { Button } from "./Button";
import { useOperation } from "../useOperation";
import { SelectField } from "./Fields";
import { useState } from "react";
import { action, useSession } from "../data";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";
import type { Params } from "../types";

type Pair = { donor: string; background: string; score: number; reasons: string[]; paste_params: Params };
export function ImagePairs({ onAttach }: { onAttach: (id: string) => void }) {
  const { busy, error, perform: work } = useOperation();
  const { data: session } = useSession();
  const [donors, setDonors] = useState<string[]>([]);
  const [backgrounds, setBackgrounds] = useState<string[]>([]);
  const [role, setRole] = useState("subject");
  const [side, setSide] = useState("center");
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [sheet, setSheet] = useState<string | null>(null);

  const ready = useUI((s) => s.status === "ready");
  const disabled = busy || !ready || !!session?.turn_running;
  const images = Object.values(session?.artifacts ?? {});

  return (
    <div>
      <p>
        Compare subject/background combinations before committing. Use prepared cutouts as donors for a
        hard-edged composite. Scores measure framing and fit; inspect expressions and the joke yourself.
      </p>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      <div className="studio-form">
        <SelectField
          label="Donor images (up to six)"
          multiple
          size={6}
          value={donors}
          onChange={(e) => setDonors(Array.from(e.target.selectedOptions, (o) => o.value).slice(0, 6))}
          options={images.map((im) => [im.id, im.label] as const)}
        />
        <SelectField
          label="Background images (up to six)"
          multiple
          size={6}
          value={backgrounds}
          onChange={(e) => setBackgrounds(Array.from(e.target.selectedOptions, (o) => o.value).slice(0, 6))}
          options={images.map((im) => [im.id, im.label] as const)}
        />
        <SelectField
          label="Role"
          bind={[role, setRole]}
          options={[
            ["subject", "Subject"] as const,
            ["head", "Head swap"] as const,
            ["object", "Object / prop"] as const,
          ]}
        />
        <SelectField
          label="Placement"
          bind={[side, setSide]}
          options={[["left", "Left"] as const, ["center", "Center"] as const, ["right", "Right"] as const]}
        />
        <Button
          disabled={disabled || !donors.length || !backgrounds.length}
          onClick={() =>
            void work(async () => {
              const step = await action("tools.run", {
                tool: "pair_images",
                params: { donors, backgrounds, role, side, n: 6 },
              });
              if (step.status !== "done")
                throw new Error(step.error?.message ?? "Could not compare image pairs.");
              setPairs((step.data?.pairs ?? []) as Pair[]);
              setSheet(step.outputs[0] ?? null);
            })
          }
          label={busy ? "Working…" : "Compare image pairs"}
        />
      </div>
      {sheet && (
        <div className="studio-sheet">
          <ArtifactThumb id={sheet} label="Image pair contact sheet" />
        </div>
      )}
      <div className="studio-grid">
        {pairs.map((pair, i) => (
          <article className="studio-card" key={`${pair.donor}-${pair.background}`}>
            <strong>Pair {i + 1}</strong>
            <span>
              {session?.artifacts[pair.donor]?.label} + {session?.artifacts[pair.background]?.label}
            </span>
            <small>{pair.reasons.join(" · ")}</small>
            <Button
              disabled={disabled}
              onClick={() =>
                void work(async () => {
                  const step = await action("tools.run", { tool: "paste", params: pair.paste_params });
                  if (step.status !== "done" || !step.outputs[0])
                    throw new Error(step.error?.message ?? "Could not compose this pair.");
                  onAttach(step.outputs[0]);
                  useUI.getState().set({
                    selectedArtifact: step.outputs[0],
                    notice: "Pair composed as an editable paste step",
                  });
                })
              }
              label="Compose this pair"
            />
          </article>
        ))}
      </div>
    </div>
  );
}
