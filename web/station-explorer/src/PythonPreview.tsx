import { useMemo } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";

/** Prism escapes source text; highlighting never changes the clipboard payload. */
export function PythonPreview({ code }: { code: string }) {
  const html = useMemo(
    () => Prism.highlight(code, Prism.languages.python, "python"),
    [code],
  );
  return (
    <pre aria-label="Python request" className="python-preview">
      <code dangerouslySetInnerHTML={{ __html: html }} />
    </pre>
  );
}
