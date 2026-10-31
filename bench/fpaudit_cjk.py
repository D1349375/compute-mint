"""False-positive audit of the fingerprints on Chinese, Japanese and Korean text.

`bench.fpaudit` covers the English repositories, which hold no CJK data. This audit asks the same question of
CJK terms: with invented customer data in the index, which texts that must stay sendable would be held back,
and how much of the data is still recognized?

  index      invented sensitive sources: small tables, JSON and prose, plus a larger generated customer table
             whose people and companies are random (so collisions are measured, not hand-picked)
  public     the repository's own Chinese plan, hand-written public tool output, and optionally `--corpus DIR`:
             text files with one public string per line (OS messages, UI strings)
  vocabulary worst case for the field rules: every short field of the public text is treated as if a sensitive
             table held it. How many would become a term, and how many public lines would each then hold back?
  mentions   sentences that repeat indexed data the way tool output would: must be caught
  misses     what the term rules are known not to catch: printed so the limit stays visible

    python -m bench.fpaudit_cjk [--corpus DIR] [--show N]
"""
import argparse
import random
import re
from collections import Counter
from pathlib import Path

from compute_mint import cjk
from compute_mint.fingerprint import SCORE, THRESHOLD, FingerprintIndex

CSV_ZH = """客戶編號,客戶名稱,聯絡人,狀態,付款條件,備註,金額,風險等級,負責業務
c-101,台灣鳳梨股份有限公司,王小明,已付款,月結45天,高優先,120000,高風險,林美華
c-102,大河電子有限公司,陳大文,處理中,貨到付款,待確認,8800,低風險,黃志強
c-103,青禾農產商行,歐陽靖,逾期未付,月結30天,重要客戶,64000,中風險,張雅婷
c-104,永昌會計師事務所,周杰倫,已取消,預付,無,0,低風險,吳宗憲
"""
JSON_ZH = """{"clients": [{"name": "北辰物流股份有限公司", "contact": "蔡依玲", "city": "高雄市", "plan": "企業版", "status": "試用中"},
 {"name": "晨光工作室", "contact": "許志安", "city": "台中市", "plan": "標準版", "status": "已續約"}]}"""
CSV_CN = """客户名称,联系人,状态,备注
华夏明珠有限责任公司,赵敏华,已付款,重点客户
东岳精密集团,孙悟饭,处理中,无
"""
CSV_JA = """会社名,担当者,状態
株式会社サクラ精機,佐藤花子,支払済
みどり商事株式会社,田中太郎,処理中
"""
CSV_KO = """회사,담당자,상태
한빛소프트 주식회사,김철수,완료
푸른바다 유한회사,박영희,진행중
"""
PROSE_ZH = """本合約由台灣鳳梨股份有限公司（以下簡稱甲方）與乙方簽署，付款條件為月結四十五天。
甲方承辦人為王小明先生，聯絡人：陳大文。逾期付款依未付金額按月計息，爭議由台北地方法院管轄。
"""
SOURCES = {"data/clients.csv": CSV_ZH, "data/clients.json": JSON_ZH, "data/kehu.csv": CSV_CN, "data/kaisha.csv": CSV_JA,
           "data/hoesa.csv": CSV_KO, "contracts/msa.md": PROSE_ZH}

MENTIONS = {
    "company, spaced": "FAILED test_invoice: 客戶 台灣鳳梨股份有限公司 與 王小明",
    "company, glued": "發票寄給台灣鳳梨股份有限公司失敗了",
    "company, no legal form": "client = 台灣鳳梨 is overdue",
    "person, spaced": "AssertionError: contact 王小明 not found",
    "person, glued": "請聯絡王小明確認金額",
    "person, json": "{'contact': '蔡依玲', 'id': 3}",
    "compound surname": "聯絡人歐陽靖未回覆",
    "org word": "收件人 永昌會計師事務所",
    "simplified company": "订单属于华夏明珠有限责任公司",
    "simplified person": "负责人赵敏华已离职",
    "japanese company": "請求先は株式会社サクラ精機です",
    "japanese person": "担当者 佐藤花子 に連絡",
    "korean company": "한빛소프트 주식회사 청구서 실패",
    "korean person": "담당자 김철수 확인",
    "prose person": "承辦人王小明先生已回信",
}
KNOWN_MISSES = {
    "other spelling": "客戶 臺灣鳳梨 逾期",
    "other script": "客户 台湾凤梨股份有限公司 逾期",
    "two-character name": "聯絡人 王明 未回覆",
    "surname not on the list": "聯絡人 那英子 未回覆",
    "ordinary-looking field": "備註 重要客戶 已更新",
    "person only in prose": "這件事由陳美玲負責",
}
PUBLIC_OUTPUT = """測試失敗：test_invoice 預期 3 實際 4
FAILED tests/test_notify.py::test_reminder - 斷言失敗
發票已寄出，付款條件為月結三十天，狀態：已付款
公司的客戶資料已匯出，共 12 筆，金額合計正確
高優先工作：修正資料庫連線逾時，連線中斷後自動重試
程式碼已合併，請檢查方法名稱與文件是否一致
負責人請確認風險等級，高風險項目需要主管核准
權限不足，無法存取資料夾，請聯絡系統管理員
銀行轉帳失敗，請稍後再試
上市公司與民營企業的報表格式不同
律師事務所的合約範本已更新
科技股份有限公司的範例資料僅供測試
這是有限公司與股份有限公司的差異說明
客戶名稱不可為空白，聯絡人欄位必填
周期性工作已排程，連線數上限為 100
金額格式錯誤，請輸入數字
王者榮耀不是這個專案的一部分
高雄市與台中市的門市資料已同步
订单状态已更新，客户名称不能为空
程序员提交了代码，测试全部通过
公司内部的文档已归档，请联系管理员
ファイルが見つかりません。接続を確認してください
株式会社と有限会社の違いについて
파일을 찾을 수 없습니다. 연결을 확인하세요
주식회사 설립 절차 안내
"""

_SURNAMES = "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴徐周葉蘇莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余盧梁趙顏柯翁魏孫戴范方宋鄧杜傅侯曹薛丁"
_GIVEN = "志明雅婷怡君家豪俊傑美玲淑芬建宏宗翰佳穎冠宇欣怡承恩詩涵柏翰子晴品妤嘉玲世昌文雄國華秀英"
_COMPANY_A = "鼎新瑞豐宏達聯發長榮統一永豐台塑亞東遠傳中興華新南亞光寶富邦仁寶緯創和碩明基友達群創"
_COMPANY_B = ["科技", "電子", "實業", "國際", "貿易", "建設", "食品", "資訊", "工業", "生技"]
_FORMS = ["股份有限公司", "有限公司", "企業社", "商行", "集團"]
_STATUSES = ["已付款", "處理中", "逾期未付", "已取消", "待確認", "高風險", "低風險", "中風險", "企業版", "標準版", "試用中", "已續約"]


def generated_table(rows: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    lines = ["客戶名稱,聯絡人,狀態"]
    for _ in range(rows):
        company = rng.choice(_COMPANY_A) + rng.choice(_COMPANY_A) + rng.choice(_COMPANY_B) + rng.choice(_FORMS)
        person = rng.choice(_SURNAMES) + rng.choice(_GIVEN) + rng.choice(_GIVEN)
        lines.append(f"{company},{person},{rng.choice(_STATUSES)}")
    return "\n".join(lines) + "\n"


def build_index(rows: int) -> FingerprintIndex:
    index = FingerprintIndex(THRESHOLD)
    for source, text in SOURCES.items():
        index.add(f"/w/{source}", text)
    if rows:
        index.add("/w/data/generated.csv", generated_table(rows))
    return index


def score(index: FingerprintIndex, text: str) -> int:
    return sum(SCORE[m.kind] for m in index.matches(text))


def public_lines(corpus: Path | None) -> dict[str, list[str]]:
    repo = Path(__file__).resolve().parent.parent
    plan = (repo / "docs" / "PLAN.md").read_text(encoding="utf-8").splitlines()
    out = {"hand-written public output": PUBLIC_OUTPUT.splitlines(), "docs/PLAN.md": [line for line in plan if line.strip()]}
    if corpus:
        for path in sorted(corpus.glob("*.txt")):
            out[path.stem] = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def audit(corpus: Path | None = None, rows: int = 2000) -> dict:
    index = build_index(rows)
    flagged = {name: [line for line in lines if score(index, line) >= THRESHOLD] for name, lines in public_lines(corpus).items()}
    return {"terms": len(index), "rows": rows, "flagged": flagged,
            "lines": {name: len(lines) for name, lines in public_lines(corpus).items()},
            "mentions": {name: score(index, text) >= THRESHOLD for name, text in MENTIONS.items()},
            "misses": {name: score(index, text) >= THRESHOLD for name, text in KNOWN_MISSES.items()}}


def vocabulary(lines: list[str]) -> dict:
    """Fields of 2-8 characters in `lines` (ordinary vocabulary) that the rules would take for a name."""
    runs = re.compile(f"[{cjk.SCRIPTS}]+")
    fields = Counter(run for line in lines for run in runs.findall(line) if 2 <= len(run) <= 8)
    named = {field: n for field, n in fields.items() if cjk.terms(field)}
    return {"fields": len(fields), "named": len(named), "occurrences": sum(fields.values()),
            "named_occurrences": sum(named.values()), "top": Counter(named).most_common(25)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--show", type=int, default=15, help="flagged lines to print per probe set")
    parser.add_argument("--rows", type=int, default=2000)
    args = parser.parse_args()
    r = audit(args.corpus, args.rows)
    print(f"Index: {len(SOURCES)} invented sources and {r['rows']} generated rows, {r['terms']} terms.\n")
    print("| Public text | Lines | Held back | Rate |\n|---|---|---|---|")
    for name, lines in r["lines"].items():
        n = len(r["flagged"][name])
        print(f"| {name} | {lines} | {n} | {n / lines:.3%} |" if lines else f"| {name} | 0 | 0 | - |")
    caught = sum(r["mentions"].values())
    print(f"\nMentions caught: {caught} / {len(r['mentions'])}; missed: {[k for k, v in r['mentions'].items() if not v]}")
    print(f"Known misses: {[k for k, v in r['misses'].items() if not v]}; caught anyway: {[k for k, v in r['misses'].items() if v]}")
    for name, lines in r["flagged"].items():
        for line in lines[:args.show]:
            print(f"held back [{name}]: {line[:120]}")
    print("\n| Vocabulary worst case | Distinct fields | Taken for a name | Share of field occurrences |\n|---|---|---|---|")
    tops = {}
    for name, lines in public_lines(args.corpus).items():
        v = vocabulary(lines)
        tops[name] = v["top"]
        if v["fields"]:
            print(f"| {name} | {v['fields']} | {v['named']} ({v['named'] / v['fields']:.2%}) | "
                  f"{v['named_occurrences'] / v['occurrences']:.3%} |")
    for name, top in tops.items():
        if top:
            print(f"most frequent [{name}]: {' '.join(f'{w}x{n}' for w, n in top)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
