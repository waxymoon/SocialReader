import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUT = "D:/SocialReader/deliverables/AI美食社媒情报Agent_笔试汇报_V2_直观证据版_20260904.pptx";
const QA = "D:/SocialReader/artifacts/ppt_revise_20260904/rendered";
const OVERVIEW = "D:/SocialReader/artifacts/ppt_overview_20260904.png";
const EVIDENCE = "D:/SocialReader/artifacts/ppt_evidence_20260904.png";
const COVER = "D:/SocialReader/artifacts/ppt_cover_20260904.png";
const CARDS = "D:/SocialReader/artifacts/ppt_cards_links_20260904.png";

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
    typeface: opts.font ?? FONT,
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

  // 2 — show the product before explaining it.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "先看结果：一个关键词，产出四类可检查结果", "01 · 产品做什么", 2);
    addRect(s, 58, 178, 720, 420, C.paper, C.line, false, "product-shot-frame");
    s.images.add({
      blob: await imageBytes(OVERVIEW), contentType: "image/png", alt: "Food intelligence current run overview",
      fit: "cover", position: { left: 72, top: 192, width: 692, height: 392 }, geometry: "rect",
    });
    const labels = [
      ["01", "关键词候选池", "保留同一次可见搜索结果"],
      ["02", "食品知识卡", "菜品、食材、味道与口感"],
      ["03", "活人感原句", "正文、评论、ASR 逐句回溯"],
      ["04", "人工审核", "通过 / 驳回 / 待确认"],
    ];
    for (let i = 0; i < labels.length; i++) {
      const y = 188 + i * 102;
      addText(s, labels[i][0], 824, y, 54, 28, { size: 16, bold: true, color: C.accent });
      addText(s, labels[i][1], 884, y - 2, 300, 32, { size: 23, bold: true });
      addText(s, labels[i][2], 884, y + 38, 310, 34, { size: 17, color: C.muted });
      if (i < 3) addRule(s, 824, y + 82, 360);
    }
    addText(s, "页面先展示事实，再把判断依据单独展开。", 824, 602, 360, 36, { size: 19, bold: true, color: C.blue });
    setNotes(s,
      "先让面试官看懂产品，再解释技术。输入一个食品关键词后，页面给出候选池、食品知识卡、可回溯原句和人工审核入口。",
      ["D:\\SocialReader\\artifacts\\ppt_overview_20260904.png", "D:\\SocialReader\\web\\food.html"]);
  }

  // 3 — process, slide-17 sequence.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "我不是只改一句话，而是把任务拆成四次判断", "02 · 优化步骤", 3);
    addText(s, "V0：输入一篇内容 → 直接输出“爆点、结构、选题灵感”", 72, 176, 920, 34, { size: 22, color: C.muted });
    addText(s, "V1：先取事实，再找原句，再审核，最后才生成推荐理由", 72, 216, 980, 36, { size: 25, bold: true });
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
    addText(s, "每一步都留下输入、输出和失败原因，错在哪里可以直接定位。", 72, 620, 1060, 36, { size: 21, bold: true, color: C.accent });
    setNotes(s,
      "V0 是一次性总结，V1 是四步流程。这样能看清是原始数据没抓到、表达没抽到、审核没通过，还是证据不足不能生成理由。",
      ["D:\\SocialReader\\domains\\food_v1\\evals\\prompt_versions.json", "D:\\SocialReader\\domains\\food_v1\\manifest.json"]);
  }

  // 4 — actual prompt excerpts.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "Prompt 前后到底改了什么？", "03 · Prompt 原文对比", 4);
    addRect(s, 58, 174, 548, 408, C.paper, C.line, false, "prompt-v0");
    addText(s, "V0 · 一段通用 Prompt", 82, 194, 470, 34, { size: 24, bold: true, color: C.accent });
    addText(s,
      "“你是社媒爆款内容分析师”\n\n“## 爆点分析（为什么火）”\n“## 可复用结构”\n“## 选题灵感”\n\n“有可复用的结构 / 方法论 / 数据 /\n趋势 / 观点才值得萃取”",
      82, 250, 486, 270, { size: 20, font: FONT });
    addText(s, "输出：title / category / tags / content", 82, 538, 480, 26, { size: 16, color: C.muted, font: "Consolas" });
    addRect(s, 646, 174, 576, 408, C.paper, C.line, false, "prompt-v1");
    addText(s, "V1 · 四段领域 Prompt", 670, 194, 500, 34, { size: 24, bold: true, color: C.blue });
    addText(s,
      "“只依据标题、正文、视频转写、评论”\n\n“exact_quote 必须逐字复制”\n“找不到证据时不得猜测”\n“不能新增候选，只负责逐条核验”\n\n“只使用已经人工审核通过的证据”\n“证据不足返回 insufficient_evidence”",
      670, 250, 514, 286, { size: 19, font: FONT });
    addText(s, "4 个文件：抽取 → 表达 → 审核 → 理由", 670, 538, 500, 26, { size: 16, color: C.muted });
    addRect(s, 58, 604, 1164, 48, C.accentSoft, C.accentSoft, false, "prompt-diff");
    addText(s, "变化：泛化总结 → 原句证据｜一次生成 → 分步审核｜有话就写 → 证据不足不生成", 78, 616, 1124, 26, { size: 18, bold: true, color: "#773322", align: "center" });
    setNotes(s,
      "左边和右边都是仓库中的真实 Prompt 原文摘录。V0 关注爆点与内容结构，适合通用知识萃取；V1 增加逐字原句、证据不足不得猜测、独立审核和人工通过后才能生成理由。",
      ["D:\\SocialReader\\extract_capture.py:148", "D:\\SocialReader\\domains\\food_v1\\prompts\\extract_food_v1.txt", "D:\\SocialReader\\domains\\food_v1\\prompts\\extract_expression_v1.txt", "D:\\SocialReader\\domains\\food_v1\\prompts\\review_evidence_v1.txt", "D:\\SocialReader\\domains\\food_v1\\prompts\\generate_reason_v1.txt"]);
  }

  // 5 — all eight contract cases.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "8 句逐条对比：V0 错 4 句，V1 全部符合预设边界", "04 · 测试结果", 5);
    const cols = [58, 580, 748, 964, 1222];
    const headers = ["测试原句", "预期", "V0 输出", "V1 输出"];
    addRect(s, 58, 174, 1164, 44, C.ink, C.ink, false, "table-header");
    for (let i = 0; i < 4; i++) addText(s, headers[i], cols[i] + 12, 185, cols[i + 1] - cols[i] - 20, 24, { size: 17, bold: true, color: C.paper });
    const rows = [
      ["虾究极 Q 弹", "保留", "保留 ✓", "保留 ✓"],
      ["每一口都能嚼到虾肉", "保留", "过滤 ✕", "保留 ✓"],
      ["求地址", "过滤", "过滤 ✓", "过滤 ✓"],
      ["好吃绝了", "过滤", "保留 ✕", "过滤 ✓"],
      ["拜见三文鱼波奇饭大王", "保留", "保留 ✓", "保留 ✓"],
      ["看起来不错", "过滤", "保留 ✕", "过滤 ✓"],
      ["这杯奶茶茶味清爽", "保留", "保留 ✓", "保留 ✓"],
      ["吃完瘦三斤", "过滤", "保留 ✕", "过滤 ✓"],
    ];
    for (let r = 0; r < rows.length; r++) {
      const y = 218 + r * 45;
      addRect(s, 58, y, 1164, 45, r % 2 ? C.paper : C.panel, r % 2 ? C.paper : C.panel, false, `row-${r}`);
      addText(s, rows[r][0], cols[0] + 12, y + 10, cols[1] - cols[0] - 20, 24, { size: 18, bold: r === 1 || r === 3 || r === 5 || r === 7 });
      addText(s, rows[r][1], cols[1] + 12, y + 10, cols[2] - cols[1] - 20, 24, { size: 17 });
      addText(s, rows[r][2], cols[2] + 12, y + 10, cols[3] - cols[2] - 20, 24, { size: 17, color: rows[r][2].includes("✕") ? C.accent : C.muted, bold: rows[r][2].includes("✕") });
      addText(s, rows[r][3], cols[3] + 12, y + 10, cols[4] - cols[3] - 20, 24, { size: 17, color: C.blue, bold: true });
    }
    addText(s, "V0：4 / 8", 66, 598, 220, 34, { size: 25, bold: true, color: C.accent });
    addText(s, "V1：8 / 8", 296, 598, 220, 34, { size: 25, bold: true, color: C.blue });
    addText(s, "仅为固定规则测试｜真实人工金标准：0 / 24｜不能当生产准确率", 560, 600, 650, 30, { size: 17, bold: true, color: C.muted, align: "right" });
    setNotes(s,
      "这一页可以直接逐行讲。四个红色叉号就是 V0 的问题：漏掉一条具体口感，误收三条泛化或风险表达；V1 在这 8 个固定边界样例中全部符合预设答案。强调这不是生产准确率。",
      ["D:\\SocialReader\\domains\\food_v1\\evals\\stage1_acceptance_cases.jsonl", "D:\\SocialReader\\deliverables\\pre_capture_demo\\eval_report.json"]);
  }

  // 6 — real run screenshot plus plain-language evidence.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "这次真实运行，页面上实际出现了什么？", "05 · 真实运行证据", 6);
    addRect(s, 58, 176, 756, 432, C.paper, C.line, false, "run-shot-frame");
    s.images.add({
      blob: await imageBytes(OVERVIEW), contentType: "image/png", alt: "Current run metrics in the application UI",
      fit: "cover", position: { left: 72, top: 190, width: 728, height: 404 }, geometry: "rect",
    });
    const evidence = [
      ["27", "候选池", "小红书当前可见搜索结果"],
      ["5 / 5", "详情成功", "小红书 3 条＋抖音 2 条"],
      ["55", "候选原句", "每条都有来源位置，仍待人工"],
      ["3 / 3", "小红书链接", "保留 xsec_token，页面可跳转"],
    ];
    for (let i = 0; i < evidence.length; i++) {
      const y = 184 + i * 104;
      addText(s, evidence[i][0], 852, y, 150, 46, { size: 34, bold: true, color: i === 1 ? C.accent : C.blue });
      addText(s, evidence[i][1], 1010, y + 4, 190, 30, { size: 20, bold: true });
      addText(s, evidence[i][2], 852, y + 50, 348, 30, { size: 16, color: C.muted });
      if (i < 3) addRule(s, 852, y + 88, 348);
    }
    addText(s, "页面数字＝当前运行快照，不随“预览关键词”伪变化。", 72, 626, 1120, 28, { size: 18, bold: true, color: C.accent });
    setNotes(s,
      "这页的左侧就是实际页面截图，右侧逐个解释数字。27 是当前可见候选池，不是全站；5/5 是本次详情采集成功；55 是候选原句，不是 55 条已确认推荐理由。",
      ["D:\\SocialReader\\artifacts\\ppt_overview_20260904.png", "D:\\SocialReader\\deliverables\\08_实施验收报告.md"]);
  }

  // 7 — traceability proof with actual links and review UI.
  {
    const s = p.slides.add(); s.background.fill = C.canvas;
    addHeader(s, "每条结果都能继续追到原链接和原句位置", "06 · 可追溯证据", 7);
    addRect(s, 58, 176, 560, 410, C.paper, C.line, false, "cards-frame");
    s.images.add({
      blob: await imageBytes(CARDS), contentType: "image/png", alt: "Food cards with original source links",
      fit: "cover", position: { left: 70, top: 188, width: 536, height: 304 }, geometry: "rect",
    });
    addText(s, "① 食品卡显示原链接", 78, 512, 500, 32, { size: 21, bold: true });
    addText(s, "可回到平台页面核对标题、作者和正文。", 78, 550, 500, 24, { size: 16, color: C.muted });
    addRect(s, 660, 176, 560, 410, C.paper, C.line, false, "evidence-frame");
    s.images.add({
      blob: await imageBytes(EVIDENCE), contentType: "image/png", alt: "Traceable expression evidence and human review controls",
      fit: "cover", position: { left: 672, top: 188, width: 536, height: 304 }, geometry: "rect",
    });
    addText(s, "② 原句显示来源与位置", 680, 512, 500, 32, { size: 21, bold: true });
    addText(s, "正文、评论、ASR 都保留来源位置与待审状态。", 680, 538, 500, 24, { size: 16, color: C.muted });
    addText(s, "现场只需要点两处：食品卡的“原链接” → 表达库的“人工通过 / 驳回”。", 72, 620, 1100, 34, { size: 19, bold: true, color: C.blue });
    setNotes(s,
      "左图证明卡片不是凭空生成：页面保留原链接。右图证明证据 ID 背后有真实原句、来源类型、位置、规则状态和人工状态。现场演示点这两处就够了。",
      ["D:\\SocialReader\\artifacts\\ppt_cards_links_20260904.png", "D:\\SocialReader\\artifacts\\ppt_evidence_20260904.png"]);
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
