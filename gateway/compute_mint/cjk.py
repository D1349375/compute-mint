"""Terms of Chinese, Japanese and Korean text for the content fingerprints (`fingerprint.py`).

These scripts have no spaces and no capital letters, and there is no segmenter or frequency list here, so an
unusual word cannot be told from an ordinary one. Only what has the *shape* of a name becomes a term:

  company  anything ending in a legal form (`股份有限公司`, `株式会社`, `주식회사`), with its tails, because in running
           text the run also holds the words before the name; in structured data the name without the legal form
  org      a whole field ending in an organization word (`銀行`, `事務所`), unless it is a generic noun
  person   a whole field of the shape surname + given name (`王小明`), unless it is an ordinary word;
           anywhere, a name after a label (`聯絡人`) or before a title (`先生`)

A field is a run of these scripts bounded by anything else: a CSV cell, a JSON value, `key: value`.
Known misses are listed in the README: two-character names, names with no surname on the list, ordinary-looking
fields, other spellings (`臺灣`/`台灣`, traditional/simplified).
"""
import re

SCRIPTS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯\U00020000-\U0002ffff"
_RUN = re.compile(f"[{SCRIPTS}]+")

MAX_PROBE_CHARS = 100_000        # of one text; the rest of a longer text is not probed
_NGRAMS = range(3, 9)            # a person or a bare company name; longer terms are anchored on a suffix
_MAX_NAME_BEFORE_SUFFIX = 16

_LEGAL = ("股份有限公司", "有限責任公司", "有限责任公司", "有限公司", "株式会社", "有限会社", "合同会社", "주식회사", "유한회사")
_ORG = ("公司", "集團", "集团", "銀行", "银行", "企業", "企业", "商行", "商社", "事務所", "事务所", "工作室", "基金會", "基金会",
        "協會", "协会", "診所", "诊所", "醫院", "医院", "会社", "회사", "은행", "법인")
_SUFFIXES = _LEGAL + _ORG
_GENERIC_ORG = frozenset("""上市公司 上櫃公司 母公司 子公司 分公司 本公司 該公司 貴公司 我們公司 這家公司 那家公司 控股公司 保險公司 物流公司
軟體公司 软件公司 科技公司 貿易公司 贸易公司 建設公司 建设公司 電信公司 电信公司 顧問公司 咨询公司 投資公司 投资公司 網路公司 互联网公司 航空公司
貨運公司 货运公司 新創公司 创业公司 外商公司 集團公司 集团公司 民營企業 民营企业 中小企業 中小企业 跨國企業 跨国企业 國營企業 国有企业 合作企業
商業銀行 商业银行 投資銀行 投资银行 中央銀行 中央银行 網路銀行 网上银行 民營銀行 律師事務所 律师事务所 會計師事務所 会计师事务所 地區醫院 综合医院
동호회사""".split())

_SURNAMES = frozenset("""陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴徐周葉蘇莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余盧梁趙顏柯翁魏孫戴范方宋鄧杜傅侯曹薛丁
卓馬阮董唐溫藍蔣石古紀姚連馮歐程湯田黎康姜汪白鄒尤巫鐘涂龔嚴韓袁金童陸夏柳邵錢伍倪于譚駱熊任甘秦顧毛章史萬俞雷粘饒
陈黄张刘杨许郑谢叶苏庄吕萧罗钟卢赵颜孙邓马蓝蒋纪连冯欧汤邹龚严韩陆钱谭骆顾万饶""".replace("\n", ""))
_COMPOUND_SURNAMES = ("歐陽", "欧阳", "司馬", "司马", "上官", "諸葛", "诸葛", "張簡", "张简", "范姜", "東方", "东方")
_JA_SURNAMES = ("佐々木", "佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "山口", "松本",
                "井上", "木村", "斎藤", "清水", "山崎", "森田", "池田", "橋本", "阿部", "石川", "前田", "藤田", "後藤", "長谷川", "村上")
_KO_SURNAMES = frozenset("김박최정강조윤임한오서권황송류홍")
# Three-character words that begin like a person's name: as a CSV cell they are vocabulary, not a person.
_NOT_NAMES = frozenset("""高品質 高品质 高風險 高风险 高優先 高优先 高效能 高效率 高可用 高速度 高中生 高鐵站 高层级 高階層 高水準 高標準 高溫度 高頻率 高負載
方法論 方法论 方便性 方向盤 方案名 金額數 金融業 金融业 金融卡 金融機 金融局 林業局 黃金價 周期性 周年慶 周转率 周轉率 周末班 葉片數 蘇打水 江南區 何時間 何種類
羅馬字 游泳池 游戏机 彭博社 胡蘿蔔 施工中 施工区 施工區 沈浸式 余额宝 顏色碼 颜色码 宋體字 宋体字 杜鵑花 傅立葉 傅里叶 侯選人 卓越獎 馬拉松 马拉松 馬達數
董事長 董事长 董事會 董事会 溫度計 溫度值 藍牙版 藍芽版 藍色的 蓝牙版 石油業 石墨烯 古典樂 古董車 紀錄檔 紀念日 紀錄表 紀錄數 纪念日 連線中 連接埠 連接數 連續性
连接数 连接中 歐元區 欧元区 程式碼 程序员 程序員 程式語 程序名 程序包 白名單 白名单 白皮書 白皮书 白色的 尤其是 嚴重性 嚴格度 严重性 韓文版 韩文版 夏令營 夏令营
任務數 任務名 任务数 任务名 任意值 任一個 顧問費 顧客數 顾客数 毛利率 章節名 章节名 萬用卡 雷射筆 雷达图 雷達圖 史丹佛 田徑隊 田径队 康復中 黎明前 曾經是 曾经是 許可證
许可证 許可權 许可权 陸續到 陆续到 鄭重其 謝謝你 谢谢你 張貼區 李子園 陳述句 吳郭魚 梁柱數 朱古力 孫子兵 鍾愛的 魏晉南 潘朵拉 洪水期 邱比特 廖化作 蕭條期 徐徐來 呂布戟
姜汁糖 汪汪隊 湯麵店 湯匙數 甘蔗汁 秦始皇 倪匡書 譚嗣同 駱駝牌 熊貓屋 熊猫屋 章魚燒 伍佰元 柳橙汁 邵氏片 錢包數 钱包数 袁世凱 童話書 童话书 龔自珍 巫師團 涂改液
戴眼鏡 范例集 范围内 鄧麗君 丁基橡 曹操傳 薛丁格 阮玲玉 唐三藏 蔣中正 姚明隊 馮諼客 俞敏洪 粘著劑 粘合剂 饒舌歌 溫泉區 温泉区""".split())

_LEGAL_FORM = re.compile("|".join(sorted(_LEGAL, key=len, reverse=True)))
# A trade, not a name: `科技股份有限公司` is the tail of every technology company.
_INDUSTRY = re.compile("(?:" + "|".join("""科技 電子 电子 實業 实业 國際 国际 貿易 贸易 建設 建设 食品 資訊 资讯 信息 工業 工业 生技 生物 投資 投资 控股 開發 开发 網路 网络
軟體 软件 系統 系统 光電 光电 能源 醫療 医疗 製造 制造 物流 商事 精機 精机 技術 技术 通信 電機 电机 機械 机械 化學 化学 金融 文化 傳媒 传媒 顧問 顾问 股份""".split()) + ")+")

_PLACE_END = tuple("市縣县區区省鄉乡鎮镇路街州島岛港灣湾國国")
_LEADING_FORMS = ("株式会社", "有限会社", "合同会社", "주식회사", "유한회사")      # these may come before the name
# Korean, and some Chinese, writes a space next to the legal form.
_SPACED_FORM = re.compile(rf"(?<=[{SCRIPTS}])[ \t]+(?={_LEGAL_FORM.pattern})|(?<={'|'.join(_LEADING_FORMS)})[ \t]+(?=[{SCRIPTS}])")
_NOT_NAME_START = tuple("""連線 連結 連接 連絡 連入 連不 连接 连线 连结 程式 程序 方法 方形 張圖 张图 钱包 游戏 鐘圖 馬來 馬加 馬德 盧森 盧安 甘比 尤拉 蘇非""".split())
_KO_PARTICLES = tuple("를을이가은는의에와과로도")
_KO_WORD_STARTS = tuple("정보 정책 권한 서비 서버 오류 오디 오른 최근 최적 최대 최소 조직 강력 박스 임시 윤곽 한국 황금 홍보".split())

_NAME = f"[{SCRIPTS}]"
_LABEL = re.compile(r"(?:聯絡人|联系人|負責人|负责人|客戶|客户|收件人|持卡人|姓名|担当者|담당자)[:\s]*"
                    f"((?:{'|'.join(_COMPOUND_SURNAMES)})?{_NAME}{{1,2}}{_NAME})")
_TITLE = re.compile(f"({_NAME}{{1,3}})(?=先生|小姐|女士|經理|经理|律師|律师|醫師|医师|會計師|会计师|様|さん|씨|님)")


def _person_shape(text: str) -> bool:
    if text in _NOT_NAMES or text.endswith(_PLACE_END) or text.startswith(_NOT_NAME_START):
        return False
    n = len(text)
    if any(text.startswith(s) and 1 <= n - len(s) <= 2 for s in _COMPOUND_SURNAMES):
        return True
    if any(text.startswith(s) and 1 <= n - len(s) <= 3 for s in _JA_SURNAMES):
        return True
    if all("가" <= c <= "힯" for c in text):
        return (n == 3 and text[0] in _KO_SURNAMES and not text.endswith(_KO_PARTICLES)
                and not text.startswith(_KO_WORD_STARTS))
    return n == 3 and text[0] in _SURNAMES


def _company_terms(run: str) -> set[str]:
    out = set()
    for m in _LEGAL_FORM.finditer(run):
        legal = m.group(0)
        before = run[:m.start()][-_MAX_NAME_BEFORE_SUFFIX:]
        tails = (before[-k:] for k in range(2, len(before) + 1))
        out.update(tail + legal for tail in tails if not _INDUSTRY.fullmatch(tail))
        # the whole run is the name: it may also come without its form
        if m.end() == len(run) and m.start() >= 3 and not _INDUSTRY.fullmatch(before):
            out.add(before)
        after = run[m.end():]
        if m.start() == 0 and legal in _LEADING_FORMS and len(after) >= 2:
            out.update((legal + after, after))
    return out


def terms(text: str, prose: bool = False) -> set[str]:
    """Name-shaped terms of `text`. `prose` drops the field rules: a clause between commas is not a field."""
    out: set[str] = set()
    text = _SPACED_FORM.sub("", text)
    for run in _RUN.findall(text):
        out |= _company_terms(run)
        if prose or len(run) > _MAX_NAME_BEFORE_SUFFIX:
            continue
        if run.endswith(_ORG) and len(run) >= 4 and run not in _GENERIC_ORG:
            out.add(run)
        if _person_shape(run):
            out.add(run)
    for pattern in (_LABEL, _TITLE):
        for m in pattern.finditer(text):
            name = m.group(1)
            for start in range(len(name)):      # the run may begin with other words: `請聯絡王小明先生`
                if _person_shape(name[start:]):
                    out.add(name[start:])
                    break
    return {t for t in out if t not in _GENERIC_ORG and t not in _SUFFIXES}


def probe_terms(text: str) -> list[str]:
    """Every string of `text` that could be a term: short n-grams, and anything ending at a suffix."""
    seen: dict[str, None] = {}
    budget = MAX_PROBE_CHARS
    for run in _RUN.findall(_SPACED_FORM.sub("", text)):
        if budget <= 0:
            break
        run = run[:budget]
        budget -= len(run)
        for n in _NGRAMS:
            for i in range(len(run) - n + 1):
                seen[run[i:i + n]] = None
        for suffix in _SUFFIXES:
            for m in re.finditer(suffix, run):
                for start in range(max(0, m.start() - _MAX_NAME_BEFORE_SUFFIX), m.start()):
                    seen[run[start:m.end()]] = None
                if m.start() == 0 and suffix in _LEADING_FORMS:
                    for end in range(m.end() + 2, min(len(run), m.end() + _MAX_NAME_BEFORE_SUFFIX) + 1):
                        seen[run[:end]] = None
    return list(seen)
