import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PythonPreview } from "./PythonPreview";
it("highlights Python tokens while escaping source text", () => {
  const rendered = renderToStaticMarkup(
    <PythonPreview
      code={
        'import rivretrieve as rr\nname = "<script>alert(1)</script>"\n# comment'
      }
    />,
  );
  expect(rendered).toContain('class="token keyword">import</span>');
  expect(rendered).toContain('class="token string"');
  expect(rendered).toContain("&lt;script>");
  expect(rendered).not.toContain("<script>");
});
