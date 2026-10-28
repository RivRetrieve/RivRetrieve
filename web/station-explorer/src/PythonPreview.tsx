import { Fragment, lazy, Suspense, type CSSProperties } from "react";
import "./python.css";

// Load only when the Python tab mounts. No bundled language or theme registry.
const HighlightedPython = lazy(async () => {
  const [
    { createHighlighterCore },
    { createJavaScriptRegexEngine },
    python,
    light,
    dark,
  ] = await Promise.all([
    import("@shikijs/core"),
    import("@shikijs/engine-javascript"),
    import("@shikijs/langs/python"),
    import("@shikijs/themes/light-plus"),
    import("@shikijs/themes/dark-plus"),
  ]);
  const highlighter = await createHighlighterCore({
    langs: [python.default],
    themes: [light.default, dark.default],
    engine: createJavaScriptRegexEngine(),
  });
  return {
    default: function HighlightedPython({ code }: { code: string }) {
      const { tokens } = highlighter.codeToTokens(code, {
        lang: "python",
        themes: { light: "light-plus", dark: "dark-plus" },
        defaultColor: false,
      });
      return (
        <code>
          {tokens.map((line, index) => (
            <Fragment key={index}>
              {index > 0 ? "\n" : null}
              {line.map((token, offset) => (
                <span key={offset} style={token.htmlStyle as CSSProperties}>
                  {token.content}
                </span>
              ))}
            </Fragment>
          ))}
        </code>
      );
    },
  };
});

/** Both themes share one escaped source; clipboard code stays with the caller. */
export function PythonPreview({ code }: { code: string }) {
  return (
    <pre aria-label="Python request" className="python-preview">
      <Suspense fallback={<code>{code}</code>}>
        <HighlightedPython code={code} />
      </Suspense>
    </pre>
  );
}
