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
  multiplierCloud: (local: number, cf: string) =>
    `Contributor + Standard requests only. ${local} local request${local === 1 ? "" : "s"} (${cf} at Standard price) not counted.`,
  multiplierTruncated: "Gateway figure: local requests count as $0 paid, so this overstates. Showing the newest 500 requests only.",
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

  flyTabLive: "Live ledger",
  flyTabBench: "Bench evidence · mock upstream",
  liveSub: (n: number) =>
    `Cumulative e, the share of tokens served by Contributor, over the ${n} requests in the ledger in the order they arrived. The dots under the plot are the lanes. A vertical line is a review decision seen while this page was open.`,
  liveTruncated: (shown: number, total: number) => `Showing the newest ${shown} of ${total} requests.`,
  liveRules: (rules: number, pending: number) => `${rules} rules learned · ${pending} paths waiting for review`,
  liveMark: (added: number) => `+${added} rule${added === 1 ? "" : "s"}`,
  liveNoMarks:
    "No review decision seen yet. Decide in the review queue, resend the held session (see the README) and the curve moves from there.",
  liveEmpty: "Not enough requests in the ledger yet.",
  liveTip: (n: number, time: string) => `request ${n} · ${time}`,
  liveE: "e so far",
  liveAxisX: "request order",

  flyTitle: "The more you review, the more can go to Contributor",
  flySub: (tasks: number, upstream: string, reviews: number) =>
    `Share of tokens served by Contributor (e), cumulative over ${tasks} tasks in the order they ran. Each review decision becomes a rule; ${reviews} decisions in this run. Bench on a ${upstream} upstream, not measured on the real API.`,
  flyAxisX: "task order",
  flyAxisY: "e, cumulative",
  flyArm: {
    standard: "All Standard",
    mint: "Mint",
    mint_learn: "Mint + rule learning",
    oracle: "Oracle ceiling",
  } as Record<string, string>,
  flyReviews: "review decisions",
  flyReviewBand: (share: number, total: number, to: number) => `${share}% of ${total} decisions made by task ${to}`,
  flyTip: (task: number, id: string) => `task ${task} · ${id}`,
  flyNote:
    "Early points swing because only a few tasks have run. After the reviews, the rule-learning arm holds close to the oracle, the same rules known from the start. The task mix is not uniform, so read the end points, not the slope.",
  flyMock: (upstream: string) => `${upstream} upstream`,
  flyFinal: (name: string) => `${name}, final`,

  dollarTitle: "Same $1, more work done",
  dollarSub: "Live ledger: the Standard price of the requests that were billed, against what was paid. Local requests are left out, not counted as free.",
  dollarStandard: "All Standard",
  dollarMint: "Compute Mint (this ledger)",
  dollarPaid: (usd: string) => `$1 of Standard-priced work cost ${usd}`,
  dollarNone: "No billed requests in this view yet.",
  dollarBenchRef: (x: string, tasks: number, upstream: string) => `bench ${x} (${tasks} tasks, ${upstream} upstream)`,
  dollarBenchNote: (x: string) => `The tick is the bench reference, Mint with rule learning at ${x}; see the Bench tab.`,

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
  multiplierCloud: (local: number, cf: string) =>
    `只算送到 Contributor 與 Standard 的請求。${local} 筆本機請求（Standard 價 ${cf}）不計入。`,
  multiplierTruncated: "Gateway 的數字：本機請求以 $0 計，會偏高。這裡只載入最新 500 筆，無法重算。",
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

  flyTabLive: "即時帳本",
  flyTabBench: "Bench 證據 · mock 上游",
  liveSub: (n: number) =>
    `帳本中 ${n} 筆請求依到達順序累計的 e（由 Contributor 處理的 token 比例）。圖下方的圓點是各請求的通道；垂直線是這個頁面開著時看到的審核決定。`,
  liveTruncated: (shown: number, total: number) => `只顯示最新 ${shown} 筆，共 ${total} 筆。`,
  liveRules: (rules: number, pending: number) => `已學到 ${rules} 條規則 · ${pending} 個路徑待審`,
  liveMark: (added: number) => `+${added} 條規則`,
  liveNoMarks: "還沒看到審核決定。在審核佇列做決定後重送被擋的 session（見 README），曲線會從那裡開始變化。",
  liveEmpty: "帳本裡的請求還不夠多。",
  liveTip: (n: number, time: string) => `第 ${n} 筆請求 · ${time}`,
  liveE: "目前的 e",
  liveAxisX: "請求順序",

  flyTitle: "審得越多，能送 Contributor 的比例越高",
  flySub: (tasks: number, upstream: string, reviews: number) =>
    `由 Contributor 處理的 token 比例（e），依執行順序在 ${tasks} 個任務上累計。每個審核決定會變成一條規則，這次共 ${reviews} 個決定。此為 ${upstream} 上游的 bench，不是真實 API 的量測。`,
  flyAxisX: "任務順序",
  flyAxisY: "e（累計）",
  flyArm: {
    standard: "全 Standard",
    mint: "Mint",
    mint_learn: "Mint + 規則學習",
    oracle: "Oracle 上限",
  } as Record<string, string>,
  flyReviews: "審核決定",
  flyReviewBand: (share: number, total: number, to: number) => `${total} 個決定中的 ${share}% 在第 ${to} 個任務前完成`,
  flyTip: (task: number, id: string) => `第 ${task} 個任務 · ${id}`,
  flyNote:
    "前段的點起伏大，是因為跑過的任務還少。審核完之後，規則學習組貼近 oracle（一開始就知道全部規則）。各階段的任務組成不一樣，請看終點，不要看斜率。",
  flyMock: (upstream: string) => `${upstream} 上游`,
  flyFinal: (name: string) => `${name}（最終）`,

  dollarTitle: "同樣 $1，完成更多工作",
  dollarSub: "即時帳本：有計費的請求，其 Standard 價與實際花費的比較。本機請求不計入，不當成免費。",
  dollarStandard: "全 Standard",
  dollarMint: "Compute Mint（這份帳本）",
  dollarPaid: (usd: string) => `Standard 價 $1 的工作，實際花 ${usd}`,
  dollarNone: "這個範圍還沒有計費的請求。",
  dollarBenchRef: (x: string, tasks: number, upstream: string) => `bench ${x}（${tasks} 個任務，${upstream} 上游）`,
  dollarBenchNote: (x: string) => `刻度線是 bench 的參考值，Mint 加規則學習 ${x}；見 Bench 分頁。`,

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
