# 開發計畫

完整架構與「可做／願景」邊界，在 Obsidian vault 的 `Side Project/競賽/Meta ai 黑客松/2026-10-27_Compute_Mint_深化架構_可做與願景邊界.md`（不隨 repo 公開）。這份只列實作順序與驗收條件。

截止：2026-11-04 9:00 PM ET（台灣 11/5 10:00）。提交前 repo 要改成公開。

## 技術選型（初版，模型選用待使用者確認）
- `gateway/`：Python 3.12＋FastAPI，提供 OpenAI 相容的 `/v1/chat/completions`。
- `dashboard/`：Next.js。
- 模型：
  - Muse Spark 1.3（`muse-spark-1.3` 與 `muse-spark-1.3-contributor`）：主要工作模型
  - Muse Glimmer（託管）：敏感度判斷、機密通道、外洩攻擊者
  - **以上都待使用者核准**
- 狀態儲存：SQLite。

## 里程碑
| 日期 | 交付 | 驗收 |
|---|---|---|
| 10/27–28 | L0 proxy、L1 標籤格與汙染傳遞、乾淨 context 組裝、L2 確定性偵測、L7 帳本 | 單元測試：含 FLOOR 祖先的項目永遠進不了 Contributor 請求；帳本的反事實成本可以重算 |
| 10/28–30 | **下一批：個人 Contributor**<br>（1）Context Broker：穩定的專案卡放在前綴、工具輸出寫入歷史前先摘要並限制長度、只在固定點做壓縮，必須顧及快取。<br>（2）個人記憶：偏好、專案事實、通過驗收的計畫。<br>（3）敏感度標籤學習：審核佇列的回饋會變成 repo／路徑標籤，也就是原本的 L8。<br>帳本加入快取命中率與私密通道成本 | 在 bench 上：Standard 通道成本下降，同時驗收通過率不降；快取命中率不低於基線；判斷準確率隨回饋上升 |
| 10/28–30（並行） | **跨 agent 前三項**（獨立 session，在自己的 worktree 開發）<br>（1）來源標籤：`Origin` 維度；Claude／GPT 的輸出永遠不能進 Contributor（Anthropic 與 OpenAI 都禁止用輸出訓練競爭模型）。<br>（2）MCP server：`delegate` 接收參照（網址、公開檔案、查詢）並套用固定範本；`recall` 讀個人記憶；個人記憶儲存。<br>（3）Codex 額度讀取（唯讀 `rate_limits`）、專案卡產生器（AGENTS.md／CLAUDE.md 標記區塊，只在 session 之間更新） | Claude／GPT 來源的內容進不了 Contributor（隨機測試）；`delegate` 的自由文字只走 Standard；額度讀取用 fixture 測試；專案卡只改標記區塊 |
| 10/29–30 | L2 Glimmer 判斷、L3 遮罩回填與 AST 化名、抽出公開子問題 | 化名後的 repo 測試結果和原版一致 |
| 10/31–11/1 | `bench/` 驗收任務集（30 題以上，依時間切分）、五組對照、L9 儀表板 | 量出 e、通過率、外洩還原率、每任務成本 |
| 10/31 晚 | 檢查點：核心完成才做 P2P 切片（stretch） | — |
| 11/2 | 紅隊外洩測試、外部試用 | — |
| 11/3 | 錄影、剪輯、公開展示頁 | — |
| 11/4 | 整理 repo、`docs/BUILD_LOG.md`、提交、改公開 | — |

## 不可違反的規則
- 金鑰只放 `.env`，絕不 commit。
- demo 和 bench 不得放入真實的 session 內容，只能用彙總數字。
- Contributor 請求一律從乾淨 context 重新組裝，不得沿用原 session 歷史。
