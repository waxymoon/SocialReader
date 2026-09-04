import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUT = "D:/SocialReader/deliverables/AI美食社媒情报Agent_笔试汇报_20260904.pptx";
const QA = "D:/SocialReader/artifacts/ppt_build_20260904/rendered";
const OVERVIEW = "D:/SocialReader/artifacts/ppt_overview_20260904.png";
const EVIDENCE = "D:/SocialReader/artifacts/ppt_evidence_20260904.png";
const COVER = "D:/SocialReader/artifacts/ppt_cover_20260904.png";

const W = 1280;
const H = 720;
const FONT = "Microsoft YaHei";
const C = {
  canvas: "#F7F4EE",
  paper: "#FFFFFF",
  ink: "#17211D",
  muted: "#65706A",
  line: "#D9D2C7",
  panel: "#ECE8E1",
  accent: "#B84D35",
  accentSoft: "#F3DDD5",
  blue: "#287A8A",
  blueSoft: "#DCEDEF",
  warning: "#D58B2B",
  warningSoft: "#F7EBCF",
};

function addRect(slide, x, y, w, h, fill, line = fill, radius = false, name = "panel") {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: line, width: line === fill ? 0 : 1 },
    ...(radius ? { borderRadius: "rounded-xl" } : {}),
  });
}

function addText(slide, text, x, y, w, h, opts = {}) {
  const box = slide.shapes.add({
    geometry: "textbox",
    name: opts.name || "text",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  box.text = text;
  box.text.style = {
    fontSize: opts.size ?? 20,
    typeface: FONT,
    color: opts.color ?? C.ink,
    bold: opts.bold ?? false,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "top",
  };
  return box;
}

function addRule(slide, x, y, w, fill = C.line, h = 2) {
  return addRect(slide, x, y, w, h, fill, fill, false, "rule");
}

function addHeader(slide, title, kicker, page) {
  addText(slide, kicker, 58, 34, 300, 24, { size: 14, bold: true, color: C.accent, name: "kicker" });
  addText(slide, title, 58, 64, 1164, 70, { size: 38, bold: true, name: "slide-title" });
  addRule(slide, 58, 144, 1164);
  addText(slide, String(page).padStart(2, "0"), 1172, 676, 50, 20, { size: 13, color: C.muted, align: "right", name: "page" });
}

function setNotes(slide, talk, sources) {
  const block = `${talk}\n\n[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}\n[/Sources]`;
  slide.speakerNotes.textFrame.setText(block);
  slide.speakerNotes.setVisible(true);
}

async function imageBytes(path) {
  const bytes = await fs.readFile(path);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function build() {
  await fs.mkdir(QA, { recursive: true });
  const p = Presentation.create({ slideSize: { width: W, height: H } });

  // 1 — cover, Codex Grid slide-08 silhouette.
  {
    const s = p.slides.add();
    s.background.fill = C.canvas;
    addText(s, "SOCIALREADER · FOOD_V1", 58, 44, 420, 26, { size: 15, bold: true, color: C.accent });
    addText(s, "AI 美食社媒\n情报 Agent", 58, 132, 530, 150, { size: 54, bold: true, name: "deck-title" });
    addText(s, "从通用采集到可追溯的领域 MVP", 58, 316, 520, 45, { size: 25, color: C.muted });
    addRule(s, 58, 394, 458, C.accent, 4);
    addText(s, "问题定义 · 规则迭代 · 测试证据 · 产品演示", 58, 426, 520, 64, { size: 20 });
    addText(s, "Shay  |  海博拓天笔试汇报  |  2026.09", 58, 630, 520, 28, { size: 15, color: C.muted });
    addRect(s, 646, 42, 576, 598, C.paper, C.line, false, "hero-frame");
    s.images.add({
      blob: await imageBytes(COVER), contentType: "image/png", alt: "SocialReader food intelligence task setup",
      fit: "cover",
      position: { left: 662, top: 58, width: 544, height: 566 }, geometry: "rect",
    });
    setNotes(s,
      "开场先讲结论：我没有重做 SocialReader，而是在通用采集底座上增加 food_v1 领域模块。这个 MVP 的重点不是声称模型更聪明，而是让新品、热门和用户原句都有可追溯的证据与明确边界。",
      ["D:\\SocialReader\\artifacts\\ppt_cover_20260904.png", "D:\\hermes\\求职\\海博拓天笔试题\\AI美食社媒情报Agent-V2任务书.md"]);
  }

  // 2 — problem / gap, slide-10 paired narrative.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "通用采集能拿到内容，但不能直接回答业务问题", "01 · 问题定义", 2);
    addText(s, "原有能力", 74, 182, 220, 34, { size: 24, bold: true, color: C.blue });
    addText(s, "抓取公开内容\n保存正文、评论与视频\n复用浏览器登录态\n输出到本地知识库", 74, 238, 430, 220, { size: 25 });
    addText(s, "价值：保留了一套可复用的采集底座", 74, 520, 430, 52, { size: 19, color: C.muted });
    addRule(s, 618, 184, 2, C.line, 424);
    addText(s, "领域判断缺口", 674, 182, 260, 34, { size: 24, bold: true, color: C.accent });
    addText(s, "“新品”缺少变更证据\n“热门”容易被误说成全站热榜\n空泛表达会混入推荐语料\n结论缺少原句与位置", 674, 238, 500, 220, { size: 25 });
    addRect(s, 674, 500, 478, 84, C.warningSoft, C.warningSoft, false, "problem-callout");
    addText(s, "核心问题不是抓不到，而是判断不可验证。", 696, 522, 436, 40, { size: 21, bold: true, color: "#7A4A0D" });
    setNotes(s,
      "这一页强调为什么要做领域升级。通用采集解决输入问题，但业务要的是可解释结论：为什么算新品、为什么相对热门、推荐理由来自哪一句。",
      ["D:\\hermes\\求职\\海博拓天笔试题\\AI美食社媒情报Agent-V2任务书.md", "D:\\SocialReader\\README.md"]);
  }

  // 3 — process, slide-17 sequence.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "V1 把一次模糊萃取拆成四个可检查步骤", "02 · 迭代路径", 3);
    addText(s, "V0：一个通用“爆款结构萃取”任务", 72, 176, 760, 34, { size: 22, color: C.muted });
    addText(s, "V1：每一步都有结构化输出、规则版本和失败状态", 72, 216, 850, 36, { size: 25, bold: true });
    addRule(s, 116, 342, 1020, C.line, 4);
    const xs = [78, 374, 670, 966];
    const nums = ["01", "02", "03", "04"];
    const titles = ["食品知识抽取", "表达候选发现", "独立证据审核", "推荐理由生成"];
    const bodies = ["菜品、食材、味道\n口感、做法、场景", "保留具体原句\n过滤泛泛描述", "检查对象、位置\n风险与可回溯性", "仅使用通过证据\n不把 ID 当结论"];
    for (let i = 0; i < 4; i++) {
      addRect(s, xs[i] + 20, 326, 34, 34, i === 3 ? C.accent : C.blue, i === 3 ? C.accent : C.blue, true, `node-${i}`);
      addText(s, nums[i], xs[i], 388, 200, 30, { size: 15, bold: true, color: C.accent });
      addText(s, titles[i], xs[i], 424, 230, 36, { size: 23, bold: true });
      addText(s, bodies[i], xs[i], 472, 235, 88, { size: 18, color: C.muted });
    }
    addText(s, "Prompt 被拆小，判断边界进入规则，最终结论保留人工审核。", 72, 620, 1060, 36, { size: 21, bold: true, color: C.accent });
    setNotes(s,
      "这里不要把 V1 讲成单纯改写了一段 Prompt。真正的变化是任务拆分：抽取、候选、审核和理由各自保存，模型或规则的错误可以被定位，而不是只看到一段最终文案。",
      ["D:\\SocialReader\\domains\\food_v1\\evals\\prompt_versions.json", "D:\\SocialReader\\domains\\food_v1\\manifest.json"]);
  }

  // 4 — before / after contract examples.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "边界样例暴露了 V0 的误收与漏收", "03 · 前后对比", 4);
    addText(s, "V0 · 宽松关键词基线", 72, 182, 470, 36, { size: 24, bold: true, color: C.muted });
    addText(s, "“好吃绝了”", 72, 246, 470, 58, { size: 34, bold: true });
    addText(s, "命中“好吃 / 绝” → 误收", 72, 316, 470, 32, { size: 20, color: C.accent });
    addText(s, "“每一口都能嚼到虾肉”", 72, 400, 470, 58, { size: 30, bold: true });
    addText(s, "未命中关键词 → 漏收", 72, 470, 470, 32, { size: 20, color: C.accent });
    addRule(s, 622, 182, 2, C.line, 382);
    addText(s, "V1 · 食品表达规则", 678, 182, 470, 36, { size: 24, bold: true, color: C.blue });
    addText(s, "泛泛夸赞，没有对象和感官细节", 678, 246, 470, 58, { size: 24, bold: true });
    addText(s, "generic noise → 过滤", 678, 316, 470, 32, { size: 20, color: C.blue });
    addText(s, "具体食材＋明确口感体验", 678, 400, 470, 58, { size: 26, bold: true });
    addText(s, "specific evidence → 保留待审", 678, 470, 470, 32, { size: 20, color: C.blue });
    addRect(s, 72, 590, 1076, 58, C.accentSoft, C.accentSoft, false, "scope-note");
    addText(s, "说明：这是固定边界样例的规则对比，不是大模型 Prompt A/B。", 94, 606, 1030, 30, { size: 18, bold: true, color: "#773322" });
    setNotes(s,
      "用两个最容易理解的例子讲清楚。V0 依赖宽松关键词，所以会把空泛夸赞收进来，也会漏掉没有预设关键词但非常具体的表达。V1 的目标是提升边界质量，而不是在这里宣称生产准确率。",
      ["D:\\SocialReader\\eval_food.py", "D:\\SocialReader\\domains\\food_v1\\evals\\stage1_acceptance_cases.jsonl"]);
  }

  // 5 — evaluation layers and gold status.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "测试夹具和人工金标准必须分开", "04 · 评测设计", 5);
    addRect(s, 64, 180, 520, 360, C.paper, C.line, false, "contract-layer");
    addText(s, "8 条", 92, 210, 220, 72, { size: 50, bold: true, color: C.blue });
    addText(s, "固定边界样例", 92, 284, 360, 36, { size: 26, bold: true });
    addText(s, "开发时预设保留/过滤答案\n用于防止规则回退\nV0 匹配 4/8，V1 匹配 8/8", 92, 346, 420, 116, { size: 21 });
    addText(s, "不能代表真实业务准确率", 92, 486, 420, 30, { size: 18, bold: true, color: C.accent });
    addRect(s, 636, 180, 520, 360, C.paper, C.line, false, "gold-layer");
    addText(s, "0 / 24", 664, 210, 260, 72, { size: 50, bold: true, color: C.accent });
    addText(s, "已完成人工金标准", 664, 284, 400, 36, { size: 26, bold: true });
    addText(s, "24 篇只是计划验收规模\n当前收集 5 篇待标内容\n主标注者、复核者均为空", 664, 346, 420, 116, { size: 21 });
    addText(s, "production_metrics = null", 664, 486, 420, 30, { size: 18, bold: true, color: C.accent });
    addText(s, "结论：现在能证明规则符合预设边界，不能声称真实准确率提升。", 72, 592, 1076, 44, { size: 22, bold: true });
    setNotes(s,
      "这页主动回答面试官可能追问的‘谁标的’。8 条是开发验收夹具；24 篇是未来计划，目前没有任何人完成标注。因此系统明确输出 production_metrics=null。",
      ["D:\\SocialReader\\domains\\food_v1\\evals\\gold_cases_v1.jsonl", "D:\\SocialReader\\deliverables\\pre_capture_demo\\eval_report.json"]);
  }

  // 6 — verified metrics, slide-19 metric-led.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "当前成果只报告可复现的工程证据", "05 · 验证结果", 6);
    addText(s, "以下数据来自本次本地运行与自动化检查；口径均限定在当前样本和当前代码。", 72, 174, 1080, 38, { size: 21, color: C.muted });
    const xs = [64, 450, 836];
    const stats = ["5 / 5", "16 / 16", "55 / 55"];
    const labels = ["真实详情采集成功", "单元与回归测试通过", "候选表达可回溯原句"];
    const desc = ["小红书 3 条＋抖音 2 条", "阶段 1–4 与通用功能回归", "仍全部处于人工待审核状态"];
    for (let i = 0; i < 3; i++) {
      addRect(s, xs[i], 280, 350, 292, i === 1 ? C.blueSoft : C.panel, i === 1 ? C.blueSoft : C.panel, false, `metric-${i}`);
      addText(s, stats[i], xs[i] + 28, 326, 294, 76, { size: 48, bold: true, color: i === 1 ? C.blue : C.ink });
      addText(s, labels[i], xs[i] + 28, 422, 294, 62, { size: 23, bold: true });
      addText(s, desc[i], xs[i] + 28, 510, 294, 42, { size: 17, color: C.muted });
    }
    addText(s, "未报告：生产准确率、平台全站热度、人工确认推荐理由。", 72, 620, 1070, 36, { size: 19, bold: true, color: C.accent });
    setNotes(s,
      "只讲三类已经复现的结果：采集成功、测试通过、证据可回溯。55 条候选不是 55 条高质量推荐语，它们仍然待人工审核。",
      ["D:\\SocialReader\\deliverables\\08_实施验收报告.md", "D:\\SocialReader\\deliverables\\pre_capture_demo\\eval_report.json"]);
  }

  // 7 — product walkthrough with two distinct screenshots.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "页面把采集、判断和人工审核连成一条演示链路", "06 · 产品功能", 7);
    addRect(s, 58, 176, 560, 390, C.paper, C.line, false, "overview-frame");
    s.images.add({
      blob: await imageBytes(OVERVIEW), contentType: "image/png", alt: "Keyword preview and current-run metrics",
      fit: "cover", position: { left: 70, top: 188, width: 536, height: 290 }, geometry: "rect",
    });
    addText(s, "① 任务设置与关键词预览", 78, 500, 500, 32, { size: 21, bold: true });
    addText(s, "预览不篡改最近运行指标；点击开始后才更新。", 78, 538, 500, 24, { size: 16, color: C.muted });
    addRect(s, 660, 176, 560, 390, C.paper, C.line, false, "evidence-frame");
    s.images.add({
      blob: await imageBytes(EVIDENCE), contentType: "image/png", alt: "Traceable expression evidence and human review controls",
      fit: "cover", position: { left: 672, top: 188, width: 536, height: 290 }, geometry: "rect",
    });
    addText(s, "② 原句证据与人工审核", 680, 500, 500, 32, { size: 21, bold: true });
    addText(s, "正文、评论、ASR 都保留来源位置与待审状态。", 680, 538, 500, 24, { size: 16, color: C.muted });
    addText(s, "演示顺序：输入关键词 → 候选池 → 详情采集 → 食品卡 → 表达审核 → 推荐理由", 72, 616, 1100, 34, { size: 20, bold: true, color: C.blue });
    setNotes(s,
      "现场演示只走最短闭环。先展示关键词预览和当前运行统计，再切换到活人感表达库，说明每条原句都能看到来源类型、位置、规则判断和人工状态。",
      ["D:\\SocialReader\\artifacts\\ppt_overview_20260904.png", "D:\\SocialReader\\artifacts\\ppt_evidence_20260904.png"]);
  }

  // 8 — close with achieved vs next.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "这个 MVP 的价值是可验证，而不是假装已经成熟", "07 · 结论与下一步", 8);
    addText(s, "已经完成", 72, 186, 320, 36, { size: 25, bold: true, color: C.blue });
    addText(s, "✓ 保留通用采集底座\n✓ 增加 food_v1 独立模块\n✓ 新品、热门、表达拆分规则\n✓ 原句、位置和审核状态可追溯\n✓ 失败与证据不足明确展示", 72, 244, 470, 250, { size: 22 });
    addRule(s, 622, 186, 2, C.line, 360);
    addText(s, "仍待完成", 678, 186, 320, 36, { size: 25, bold: true, color: C.accent });
    addText(s, "→ 重构食品层级与多维属性\n→ 完成 24 篇人工金标准\n→ 双人复核并计算真实指标\n→ 处理 ASR 错字与令牌过期\n→ 扩大同平台候选池验证", 678, 244, 470, 250, { size: 22 });
    addRect(s, 72, 570, 1076, 72, C.accent, C.accent, false, "closing-statement");
    addText(s, "先让每个结论站得住，再逐步追求更高的自动化。", 100, 588, 1020, 38, { size: 26, bold: true, color: C.paper, align: "center" });
    setNotes(s,
      "收尾回到开场：这个版本不是完成所有智能判断，而是把一个容易夸大的演示题做成可验证、可追溯、可继续迭代的 MVP。下一步优先补真实人工金标准和专业品类体系。",
      ["D:\\SocialReader\\deliverables\\05_已知限制与后续计划.md", "D:\\SocialReader\\deliverables\\08_实施验收报告.md"]);
  }

  for (const [i, s] of p.slides.items.entries()) {
    const stem = `slide-${String(i + 1).padStart(2, "0")}`;
    const png = await p.export({ slide: s, format: "png", scale: 1 });
    await fs.writeFile(`${QA}/${stem}.png`, new Uint8Array(await png.arrayBuffer()));
    const layout = await s.export({ format: "layout" });
    await fs.writeFile(`${QA}/${stem}.layout.json`, await layout.text());
  }
  const montage = await p.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(`${QA}/montage.webp`, new Uint8Array(await montage.arrayBuffer()));
  const pptx = await PresentationFile.exportPptx(p);
  await pptx.save(OUT);
  console.log(`WROTE ${OUT}`);
}

build().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
