import "./icons.css";
export type GaugeState = "match" | "selected" | "conflict";
export const pinPath =
  "M16 1C8.3 1 2 7.1 2 14.8C2 24 16 38 16 38S30 24 30 14.8C30 7.1 23.7 1 16 1Z";
export const staffPath = "M11 8V23M11 9H15M11 13H14M11 17H15M11 21H14";
export const riverPath = "M18 15Q20 12 22 15T26 15M18 21Q20 18 22 21T26 21";
export const badgePaths = {
  selected: "M21 7L24 10L29 4",
  conflict: "M25 3V7M25 10V10.5",
};

/** Static geometry only; station source text never enters SVG markup. */
export function gaugePinSvg(state: GaugeState) {
  const badge =
    state === "match"
      ? ""
      : `<circle class="gauge-badge" cx="25" cy="7" r="7"/><path data-badge="${state === "selected" ? "check" : "warning"}" class="gauge-badge-mark" d="${badgePaths[state]}"/>`;
  return `<svg class="gauge-symbol" data-state="${state}" viewBox="0 0 34 40" aria-hidden="true"><path class="gauge-body" d="${pinPath}"/><path data-part="staff" class="gauge-measurement" d="${staffPath}"/><path data-part="river" class="gauge-measurement" d="${riverPath}"/>${badge}</svg>`;
}
export function GaugeIcon({ state }: { state: GaugeState }) {
  return (
    <span
      className="gauge-icon"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: gaugePinSvg(state) }}
    />
  );
}

/** Cache three small raster sprites per palette instead of adding selected DOM markers. */
export function gaugeSprites(host: HTMLElement, ratio: number) {
  const style = getComputedStyle(host);
  return Object.fromEntries(
    (["selected", "conflict"] as const).map((state) => {
      const canvas = document.createElement("canvas");
      canvas.width = 34 * ratio;
      canvas.height = 40 * ratio;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(ratio, ratio);
      const color = style.getPropertyValue(`--gauge-${state}`).trim();
      const ink = style.getPropertyValue("--gauge-ink").trim();
      ctx.fillStyle = color;
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1.3;
      const path = new Path2D(pinPath);
      ctx.fill(path);
      ctx.stroke(path);
      ctx.strokeStyle = ink;
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.stroke(new Path2D(staffPath));
      ctx.stroke(new Path2D(riverPath));
      ctx.beginPath();
      ctx.arc(25, 7, 7, 0, Math.PI * 2);
      ctx.fillStyle = ink;
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.4;
      ctx.stroke(new Path2D(badgePaths[state]));
      return [state, canvas];
    }),
  ) as Record<"selected" | "conflict", HTMLCanvasElement>;
}
