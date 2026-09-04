import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source = "D:/SocialReader/artifacts/ppt_revise_20260904/source.pptx";
const out = "D:/SocialReader/artifacts/ppt_revise_20260904/source-inspect";
await fs.mkdir(out, { recursive: true });
const p = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await p.inspect({
  kind: "slide,textbox,shape,image,table,chart,notes,layout",
  include: "id,slide,name,title,textPreview,textChars,textLines,bbox,bboxUnit,alt,isPlaceholder,placeholders",
  maxChars: 50000,
});
await fs.writeFile(`${out}/source-inspect.ndjson`, snapshot.ndjson, "utf8");
for (const [i, slide] of p.slides.items.entries()) {
  const stem = `slide-${String(i + 1).padStart(2, "0")}`;
  const png = await p.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(`${out}/${stem}.png`, new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(`${out}/${stem}.layout.json`, await layout.text());
}
const layouts = await p.inspect({ kind: "layout", maxChars: 20000 });
await fs.writeFile(`${out}/layouts.ndjson`, layouts.ndjson, "utf8");
console.log(`slides=${p.slides.items.length}`);
