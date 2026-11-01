import styles from "../../core/src/badshop/agent/creative_styles.json";

export const creativeStyles = styles;

/** Keep the user's ordinary request byte-for-byte unless they choose a direction. */
export function creativeRequest(text: string, styleId: string, takes: 1 | 3): string {
  const style = creativeStyles.find((item) => item.id === styleId);
  const instructions: string[] = [];
  if (style) instructions.push(`Creative style: ${style.name} (${style.id}). ${style.summary}`);
  if (takes === 3)
    instructions.push(
      "Make three distinct takes of this request. First name three different premises or " +
      "compositions, then create a separate finished image for each. Start each from its own " +
      "clean base, reusing the original subject; do not stack one take on another. Label the " +
      "final artifact ids Take 1, Take 2, and Take 3 so I can compare them. Keep the selected " +
      "style across the takes if one is specified.",
    );
  return instructions.length ? `${text.trim()}\n\n${instructions.join("\n")}`.trim() : text;
}
