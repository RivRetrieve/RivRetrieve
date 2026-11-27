import { useId, useState } from "react";

/** Accessible warning tooltip supporting hover, keyboard focus, Escape, and touch tap. */
export function CoordinateWarning({ children }: { children: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="coordinate-warning"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={(event) => {
        if (!event.currentTarget.contains(document.activeElement))
          setOpen(false);
      }}
    >
      <button
        type="button"
        className="coordinate-warning-trigger"
        aria-label="Coordinate reference warning"
        aria-describedby={id}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span aria-hidden="true">⚠</span>
      </button>
      <span
        id={id}
        role="tooltip"
        className="coordinate-warning-tooltip"
        hidden={!open}
      >
        {children}
      </span>
    </span>
  );
}
