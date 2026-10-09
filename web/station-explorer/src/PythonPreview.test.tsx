import { expect, it } from "vitest";
import { renderToReadableStream, renderToStaticMarkup } from "react-dom/server";
import { PythonPreview } from "./PythonPreview";

const code =
  'import rivretrieve as rr\nname = "<script>alert(1)</script>"\n# comment\n';

it("shows escaped plain Python while the highlighter loads", () => {
  const rendered = renderToStaticMarkup(<PythonPreview code={code} />);
  expect(rendered).toContain("<code>import rivretrieve as rr\nname = &quot;");
  expect(rendered).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  expect(rendered).not.toContain("<script>");
});

it("uses VS Code Light+ and Dark+ token colors without changing the source", async () => {
  const stream = await renderToReadableStream(<PythonPreview code={code} />);
  await stream.allReady;
  const rendered = await new Response(stream).text();
  // Official VS Code themes: import is a control keyword; strings are red/orange.
  expect(rendered).toMatch(
    /style="[^"]*--shiki-light:#AF00DB;[^"]*--shiki-dark:#C586C0[^"]*">import<\/span>/,
  );
  expect(rendered).toMatch(
    /style="[^"]*--shiki-light:#A31515;[^"]*--shiki-dark:#CE9178[^"]*">/,
  );
  expect(rendered).not.toContain("<script>");
  const text = rendered
    .replace(/<[^>]*>/g, "")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'")
    .replaceAll("&amp;", "&");
  expect(text).toBe(code);
});
