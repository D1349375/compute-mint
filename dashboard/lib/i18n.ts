import type { Lane } from "./types";

export type Lang = "en" | "zh";

const en = {
  tagline: "A gateway between agents and models: public work goes to Contributor in a clean, masked context.",
  allSessions: "All sessions",
  session: "Session",
  live: "Live",
  offline: "Gateway offline",
  offlineHelp: "Start the gateway on the demo data (see dashboard/README.md), then this page refreshes by itself.",
  refreshed: "updated",

  billingMode: "Billing mode",
  credits: "Credits",
  paid: "Paid",
  creditsWhy:
    "On promotional credits every request counts as non-paid use (ToS §13.3) and may be used for training — Standard included (§6.2). So whatever may not go to Contributor never reaches Meta: a local model runs it, or the gateway holds it.",
  paidWhy:
    "Paid use is not used for training (ToS §5.1), so a request that may not go to Contributor goes to Standard.",
  fallback: "Not contributable →",
  fallbackLocal: (m: string) => `local model ${m}`,
  fallbackHeld: "held (403), no local model configured",
  fallbackStandard: "Standard",

  saved: "Saved",
  vsStandard: "vs. sending everything to Standard",
  paidLabel: "Paid",
  counterfactual: "All-Standard cost",
  multiplier: "Effective compute",
  multiplierSub: "counterfactual ÷ paid",
  eShare: "Contributable tokens",
  eSub: "share of tokens served by Contributor (e)",
  cacheHit: "Cache hit rate",
  cacheSub: "cached ÷ prompt tokens",
  creditsUsed: "Credits used",
  creditsSub: "spend while on promotional credits",
  stayed: "Stayed on this machine",
  stayedSub: (local: number, held: number) => `${local} ran locally · ${held} held`,
  requests: "requests",

  laneMix: "Where requests went",
  byRequests: "Requests",
  byTokens: "Tokens",
  timeline: "Timeline",
  timelineSub: "Every request, by lane. Hover a dot for its reason.",

  leftTitle: "What left this machine",
  leftSub: "The exact masked context of a Contributor request. Placeholders stand in for values that never left.",
  placeholders: "placeholders",
  noPayload: "No Contributor request in this view yet.",
  systemPrompt: "system prompt",
  showAll: "show",
  hide: "hide",
  chars: "chars",
  request: "Request",
  toolCall: "tool call",

  reviewTitle: "Review queue",
  reviewSub:
    "Files with no rule are treated as confidential and kept off Contributor. One decision becomes a rule for every matching file — the more you review, the more you save.",
  heldBack: (n: number) => `held back ${n} request${n === 1 ? "" : "s"}`,
  pattern: "Rule pattern",
  public: "Public",
  own_ip: "Own IP",
  confidential: "Confidential",
  rules: "Learned rules",
  noPending: "Nothing waiting for review.",
  noRules: "No rules yet.",
  replayHint: "After a decision, resend the held sessions: python -m demo.seed --replay",

  tableTitle: "Requests",
  time: "Time",
  lane: "Lane",
  billing: "Billing",
  tokens: "Tokens (cached)",
  cost: "Cost",
  cf: "All-Standard",
  reason: "Reason",
  masked: "Masked",
  prev: "Newer",
  next: "Older",
  of: "of",

  benchTitle: "Bench evidence",
  benchSub: (tasks: number, upstream: string) =>
    `${tasks} synthetic coding tasks with deterministic acceptance, ${upstream} upstream. Canary values are planted secrets and personal data that must never reach Contributor.`,
  arm: "Arm",
  acceptance: "Acceptance",
  e: "e (Contributor tokens)",
  computeX: "Compute ×",
  canary: "Canary violations",
  notExecuted: "simulated, not sent",
  benchMissing: "Bench results not found.",
  footer:
    "Compute Mint · invented demo data from bench/materials · not affiliated with or endorsed by any model provider.",
};

export type Strings = typeof en;

const zh: Strings = {
  tagline: "agent 與模型之間的閘道：可公開的工作以遮罩後的乾淨 context 送到 Contributor。",
  allSessions: "全部 session",
  session: "Session",
  live: "連線中",
  offline: "Gateway 未連線",
  offlineHelp: "依 dashboard/README.md 用 demo 資料啟動 gateway，這頁會自動更新。",
  refreshed: "更新於",

  billingMode: "計費模式",
  credits: "促銷額度",
  paid: "付費",
  creditsWhy:
    "用促銷額度時，每筆請求都算非付費服務（ToS §13.3），連 Standard 也可能被拿去訓練（§6.2）。所以不能送 Contributor 的內容一律不送到 Meta：交給本機模型，沒有就擋下。",
  paidWhy: "付費使用不會被拿去訓練（ToS §5.1），所以不能送 Contributor 的請求改走 Standard。",
  fallback: "不能貢獻的請求 →",
  fallbackLocal: (m: string) => `本機模型 ${m}`,
  fallbackHeld: "擋下（403），未設定本機模型",
  fallbackStandard: "Standard",

  saved: "省下",
  vsStandard: "相較於全部走 Standard",
  paidLabel: "實際花費",
  counterfactual: "全走 Standard",
  multiplier: "有效算力",
  multiplierSub: "對照成本 ÷ 實際花費",
  eShare: "可貢獻 token",
  eSub: "由 Contributor 處理的 token 比例（e）",
  cacheHit: "快取命中率",
  cacheSub: "快取 token ÷ 輸入 token",
  creditsUsed: "已用額度",
  creditsSub: "使用促銷額度期間的花費",
  stayed: "留在本機",
  stayedSub: (local: number, held: number) => `本機執行 ${local} 筆 · 擋下 ${held} 筆`,
  requests: "筆請求",

  laneMix: "請求去向",
  byRequests: "請求數",
  byTokens: "Token",
  timeline: "時間軸",
  timelineSub: "每筆請求依通道排列，滑過圓點看原因。",

  leftTitle: "離開本機的內容",
  leftSub: "Contributor 請求實際送出的遮罩後 context。placeholder 代表沒有離開本機的原值。",
  placeholders: "個 placeholder",
  noPayload: "這個範圍內還沒有 Contributor 請求。",
  systemPrompt: "系統提示",
  showAll: "展開",
  hide: "收合",
  chars: "字元",
  request: "請求",
  toolCall: "工具呼叫",

  reviewTitle: "審核佇列",
  reviewSub: "沒有規則的檔案一律當作機密，不送 Contributor。一個決定會變成規則套用到所有相符的檔案——審得越多，省得越多。",
  heldBack: (n: number) => `擋下 ${n} 筆請求`,
  pattern: "規則樣式",
  public: "公開",
  own_ip: "自有 IP",
  confidential: "機密",
  rules: "已學到的規則",
  noPending: "沒有待審項目。",
  noRules: "還沒有規則。",
  replayHint: "做完決定後重送被擋的 session：python -m demo.seed --replay",

  tableTitle: "請求明細",
  time: "時間",
  lane: "通道",
  billing: "計費",
  tokens: "Token（快取）",
  cost: "花費",
  cf: "全走 Standard",
  reason: "原因",
  masked: "遮罩",
  prev: "較新",
  next: "較舊",
  of: "／",

  benchTitle: "Bench 證據",
  benchSub: (tasks: number, upstream: string) =>
    `${tasks} 個合成程式任務，各有確定性驗收，上游為 ${upstream}。金絲雀是預先埋入、絕不能送到 Contributor 的假秘密與假個資。`,
  arm: "組別",
  acceptance: "驗收通過",
  e: "e（Contributor token）",
  computeX: "算力倍數",
  canary: "金絲雀違規",
  notExecuted: "僅模擬，未送出",
  benchMissing: "找不到 bench 結果。",
  footer: "Compute Mint · demo 資料取自 bench/materials 的虛構內容 · 與任何模型供應商無隸屬或背書關係。",
};

export const STRINGS: Record<Lang, Strings> = { en, zh };

export const LANE_NAMES: Record<Lang, Record<Lane, string>> = {
  en: { contributor: "Contributor", standard: "Standard", local: "Local", held: "Held" },
  zh: { contributor: "Contributor", standard: "Standard", local: "本機", held: "擋下" },
};

export const LANE_NOTES: Record<Lang, Record<Lane, string>> = {
  en: {
    contributor: "clean masked context, discounted",
    standard: "private only when paid",
    local: "never left this machine",
    held: "not sent anywhere",
  },
  zh: {
    contributor: "遮罩後的乾淨 context，折扣價",
    standard: "只有付費時才不被訓練",
    local: "沒有離開本機",
    held: "沒有送到任何地方",
  },
};
