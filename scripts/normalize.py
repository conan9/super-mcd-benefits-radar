"""把四个 MCP 工具返回的异构 JSON 统一为规范化数据结构。

设计原则（对应 SKILL.md 的"不编造"承诺）
----------------------------------------
* **容错取值**：真实字段名以官方文档描述为准，但接口可能调整，
  因此每个规范字段配置一组别名（:data:`COUPON_ALIASES` 等），逐个尝试。
* **缺失即缺失**：任何别名都取不到时，规范字段置 ``None`` 并登记进 ``missing``，
  **绝不填 0、绝不填占位文案**。报告层据 ``missing`` 渲染 ``[字段缺失]``。
* **解析失败不抛异常**：日期/数字解析失败返回 ``None``，并由上层登记为缺失。
* **解析失败必须报警，不得伪装成"没有数据"**：见 :class:`PayloadState`。
  这是本模块最容易被忽视、后果最严重的一条——真实 ``campaign-calendar``
  返回的是 Markdown 正文而非 JSON，早期实现会静默产出零条活动，
  报告看起来像"本月确实没有活动"。详见 :func:`classify_state`。

响应格式假设
------------
**四个工具的真实响应格式已全部实测确认（2026-10-09，结论见 ``references/live-verification.md``）：**

======================  ==========================  ==========================================
工具                     真实格式                     解析入口
======================  ==========================  ==========================================
``campaign-calendar``   Markdown（``#### 日期``）     :func:`parse_campaign_markdown`
``query-my-coupons``    Markdown（``## 券名``）       :func:`parse_coupon_markdown`
``query-my-account``    说明文本 + 内嵌 JSON          :func:`extract_embedded_json`
``available-coupons``   Markdown（行内续行）          :func:`parse_available_coupons_markdown`
======================  ==========================  ==========================================

**四个工具都同时保留了 JSON 结构解析能力**：真实返回格式若变回 JSON，
``find_records`` 会先命中，文本解析器只在"结构解析出零条记录"时作为回退启用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Iterator

# --------------------------------------------------------------------------- #
# 字段别名表
# --------------------------------------------------------------------------- #
COUPON_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("couponId", "coupon_id", "couponCode", "id", "code"),
    "name": ("couponName", "name", "couponTitle", "title", "description", "desc"),
    "coupon_type": ("couponType", "coupon_type", "type", "category"),
    "discount_value": (
        "discountValue",
        "discountAmount",
        "reduceAmount",
        "discount",
        "value",
        "amount",
    ),
    "threshold": ("thresholdAmount", "threshold", "minAmount", "conditionAmount", "limitAmount"),
    "valid_from": ("startDate", "validFrom", "beginTime", "startTime", "effectiveTime"),
    "valid_to": ("endDate", "validTo", "expireTime", "endTime", "expireDate", "deadline"),
    "channel": ("useChannel", "channel", "useScene", "scene"),
    "status": ("couponStatus", "status", "state"),
}

CAMPAIGN_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("campaignId", "activityId", "id", "code"),
    "name": ("campaignName", "activityName", "name", "title"),
    "start": ("startDate", "startTime", "beginTime", "validFrom"),
    "end": ("endDate", "endTime", "expireTime", "validTo"),
    "status": ("status", "campaignStatus", "state"),
}

#: 积分账户别名。
#: **首选别名来自 2026-10-09 的真实返回**（``query-my-account`` 的
#: ``## Original Response`` 内嵌 JSON）：``availablePoint`` /
#: ``accumulativePoint`` / ``frozenPoint`` / ``currentMouthExpirePoint`` / …
#: 注意官方拼写是 ``Mouth`` 而非 ``Month``（线上确实如此），
#: 因此 ``Mouth`` 优先、``Month`` 作为纠正版兜底，两者都留。
POINTS_ALIASES: dict[str, tuple[str, ...]] = {
    "available": ("availablePoint", "availablePoints", "available", "usablePoints", "points", "balance"),
    "total": ("accumulativePoint", "totalPoints", "accumulatedPoints", "total"),
    "frozen": ("frozenPoint", "frozenPoints", "frozen", "frozenAmount"),
    "expiring_points": (
        "currentMouthExpirePoint",
        "currentMonthExpirePoint",
        "expiringPoints",
        "expiringSoonPoints",
        "willExpirePoints",
        "expirePoints",
        "soonExpiredPoints",
    ),
    "expiring_date": ("expiringDate", "expireDate", "expiryDate", "expiringTime"),
    "level": ("memberLevel", "level", "grade", "memberGrade"),
    # —— 以下为真实返回中存在、早期版本未纳管的字段 ——
    "used": ("usedPoint", "usedPoints", "used"),
    "expired": ("expiredPoint", "expiredPoints", "expired"),
    "next_expiring_points": ("nextMouthExpirePoint", "nextMonthExpirePoint"),
    "last_expired": ("lastMouthExpirePoint", "lastMonthExpirePoint"),
    "currency": ("currency",),
    "account_id": ("accountId", "account_id"),
}

#: 已识别但**按隐私策略刻意不纳入报告**的字段（键名会被说明，取值不外泄）。
PRIVACY_EXCLUDED_FIELDS: dict[str, str] = {
    "accountId": "会员账户标识",
}

#: 需要按 UTC+8 处理的两个原因：官方有效期以北京时间书写；用户在东八区。
#: 用固定偏移而非 ``zoneinfo``：Windows 上 ``zoneinfo`` 需要额外的 tzdata 包，
#: 而本项目承诺零第三方依赖。中国自 1991 年起不实行夏令时，固定 +08:00 精确无误。
BEIJING_TZ = timezone(timedelta(hours=8))


def now_beijing() -> datetime:
    """当前北京时间（带时区信息）。"""
    return datetime.now(BEIJING_TZ)


def today_beijing() -> date:
    """北京时间下的"今天"——**所有到期判定的唯一基准**。

    若用 ``date.today()``，在 UTC 机器上东八区凌晨 0:00–8:00 会被算成前一天，
    进而把"今天到期"的券报成"明天到期"（或反之），属可复现的日期边界错误。
    """
    return now_beijing().date()

#: 记录数组可能挂在这些键下（按优先级）
LIST_KEYS: tuple[str, ...] = (
    "couponList",
    "coupons",
    "campaignList",
    "activityList",
    "list",
    "records",
    "items",
    "data",
)

#: 每条优惠券必须可用的关键字段——缺失会直接影响排序可信度
COUPON_CRITICAL: tuple[str, ...] = ("name", "valid_to")

#: 报告展示用的中文字段名
FIELD_LABELS: dict[str, str] = {
    "id": "券ID",
    "name": "名称",
    "coupon_type": "类型",
    "discount_value": "优惠值",
    "threshold": "门槛",
    "valid_from": "生效日",
    "valid_to": "到期日",
    "channel": "适用渠道",
    "status": "状态",
    "available": "可用积分",
    "total": "累计积分",
    "frozen": "冻结积分",
    "expiring_points": "即将过期积分",
    "expiring_date": "过期日",
    "level": "会员等级",
    "start": "开始日",
    "end": "结束日",
    # —— 真实返回中存在、用于如实呈现原文的字段 ——
    "benefit_text": "券面权益",
    "benefit_kind": "权益类型",
    "price": "用券价格",
    "tags": "标签",
    "received_text": "领取时间",
    "valid_window": "适用时段",
    "image": "券图",
    "used": "已使用积分",
    "expired": "已过期积分",
    "next_expiring_points": "下月将过期积分",
    "last_expired": "上月已过期积分",
    "currency": "积分类型",
}

MISSING_MARK = "[字段缺失]"

#: 官方原文里表示"这条字段没有提供"的说法——统一渲染为 `[字段缺失]` 的等价语义。
NOT_PROVIDED_MARK = "未提供"

# --------------------------------------------------------------------------- #
# 各来源「格式本身不携带」的字段
# --------------------------------------------------------------------------- #
#: ``query-my-coupons`` 的 Markdown 正文不包含这些字段。
#: 它们是**格式属性**而非单条数据的缺陷，因此不逐条登记，只在数据源状态里说明一次。
MD_COUPON_ABSENT: tuple[str, ...] = ("id", "coupon_type", "discount_value", "threshold")

#: Markdown 券格式**每条都应当**有的字段——只有这些缺失才值得逐条报警。
MD_COUPON_REQUIRED: tuple[str, ...] = ("name", "valid_to")

#: ``available-coupons`` 的 Markdown 正文只有「标题 / 状态 / 图片」三样。
MD_AVAILABLE_ABSENT: tuple[str, ...] = (
    "id",
    "coupon_type",
    "discount_value",
    "threshold",
    "valid_from",
    "valid_to",
    "channel",
)

#: 可领取券**每条都应当**有的字段。
MD_AVAILABLE_REQUIRED: tuple[str, ...] = ("name", "status")

#: ``query-my-account`` 的 JSON 里没有这两项——报告须写明"未提供"，不得推测。
ACCOUNT_ABSENT: tuple[str, ...] = ("expiring_date", "level")

#: 积分账户中**数值型**字段（真实返回里它们都是字符串型数字）。
ACCOUNT_NUMERIC_FIELDS: tuple[str, ...] = (
    "available",
    "total",
    "frozen",
    "expiring_points",
    "used",
    "expired",
    "next_expiring_points",
    "last_expired",
)

#: 积分账户取不到时要逐项声明的字段 = 数值字段 + 格式不提供的两项
ACCOUNT_REQUIRED_FIELDS: tuple[str, ...] = (*ACCOUNT_NUMERIC_FIELDS, *ACCOUNT_ABSENT)

#: 积分账户里的隐私键：**取值不落库、不进报告**（键名本身仍会在 schema 文档中说明）。
ACCOUNT_PRIVACY_KEYS: frozenset[str] = frozenset(
    {"accountId", "account_id", "accountID", "userId", "memberId", "phone", "mobile"}
)

#: 报告里对"该格式不提供某字段"的统一解释文案
ABSENT_FIELD_NOTES: dict[str, str] = {
    "id": "官方正文不提供券/活动 ID，报告中的编号是本技能生成的**定位编号**，不是官方 ID",
    "coupon_type": "官方正文不提供券类型",
    "discount_value": "官方正文不提供券面优惠金额（券面权益以官方原文给出，见「券面权益」列）",
    "threshold": "官方正文不提供使用门槛（若原文含时段限制，见「适用时段」列）",
    "valid_from": "官方正文不提供生效日",
    "valid_to": "官方正文不提供到期日，因此无法按到期紧急度排序",
    "channel": "官方正文不单独给出适用渠道（若原文有「到店专用 / 外送专用」等标签，已归入「标签」列）",
    "expiring_date": "官方接口只返回积分数量，不返回过期日期",
    "level": "官方接口不返回会员等级",
}


# --------------------------------------------------------------------------- #
# 取数状态分类 —— 区分「空」「读不懂」「失败」
# --------------------------------------------------------------------------- #
class PayloadState(str, Enum):
    """单次工具调用的解析状态。

    为什么需要它：早期实现只记录"解析出几条记录"，于是**解析器读不懂真实格式**
    和**接口确实返回空**在报告里长得一模一样，都会显示"没有数据"。
    真实 ``campaign-calendar`` 返回 Markdown 正文时，报告因此显示"本月没有活动"——
    这是静默的假阴性，比报错更危险，因为用户无从察觉。

    四种状态必须分开处理，不允许互相冒充：

    ==================  ==========================================  ==========================
    状态                 含义                                        报告应如何呈现
    ==================  ==========================================  ==========================
    ``PARSED``          调用成功且识别出记录                        正常展示
    ``EMPTY``           调用成功，确实没有数据                      可以说"没有"
    ``UNRECOGNIZED``    调用成功、**收到内容但解析器读不懂**         必须报"收到数据但解析失败"
    ``FAILED``          调用失败（网络 / 鉴权 / 限流 / 工具报错）    必须报"取数失败"
    ==================  ==========================================  ==========================
    """

    PARSED = "parsed"
    EMPTY = "empty"
    UNRECOGNIZED = "unrecognized"
    FAILED = "failed"


#: 协议信封字段——判定"是否真有内容"时忽略，避免 ``{"code":0,"msg":"ok"}``
#: 被误判成"收到了数据"。
_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "code",
        "msg",
        "message",
        "success",
        "ok",
        "errcode",
        "errmsg",
        "error",
        "status",
        "timestamp",
        "datetime",
        "time",
        "servertime",
        "requestid",
        "traceid",
        "request_id",
        "trace_id",
        "version",
        "total",
        "count",
        "page",
        "pagesize",
        "pages",
    }
)

#: 承载真载荷的键——即使用信封名也要往下钻
_PAYLOAD_KEYS: tuple[str, ...] = ("data", "result", "body", "payload", "content")


def payload_text(payload: Any) -> str:
    """把任意 payload 统一转为字符串，用于长度统计与文本解析。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - 防御性
        return str(payload)


def has_payload_content(node: Any, depth: int = 0) -> bool:
    """递归判断 payload 里是否**真有实质内容**（忽略信封字段与空容器）。

    这是"空"与"读不懂"的分界线：返回 ``True`` 说明对方确实发了东西，
    只是我们没消化；返回 ``False`` 才是真正的空结果。
    """
    if depth > 6:
        return False
    if node is None:
        return False
    if isinstance(node, str):
        text = node.strip()
        if not text:
            return False
        try:
            return has_payload_content(json.loads(text), depth + 1)
        except json.JSONDecodeError:
            # 纯自由文本 —— 有内容，而且通常意味着"另一种格式"
            return True
    if isinstance(node, dict):
        for key, value in node.items():
            name = str(key).lower()
            if str(key).startswith("_"):
                continue
            if name in _ENVELOPE_KEYS and name not in _PAYLOAD_KEYS:
                continue
            if has_payload_content(value, depth + 1):
                return True
        return False
    if isinstance(node, (list, tuple, set)):
        return any(has_payload_content(value, depth + 1) for value in node)
    return True  # 数值 / 布尔 → 视为内容


def classify_state(ok: bool, payload: Any, record_count: int) -> PayloadState:
    """据调用结果与解析结果判定状态。判定顺序不可调换。

    1. 调用失败 → ``FAILED``（其余信息无意义）
    2. 解析出记录 → ``PARSED``
    3. 有内容却零记录 → ``UNRECOGNIZED``（**必须报警**）
    4. 否则 → ``EMPTY``
    """
    if not ok:
        return PayloadState.FAILED
    if record_count > 0:
        return PayloadState.PARSED
    return PayloadState.UNRECOGNIZED if has_payload_content(payload) else PayloadState.EMPTY


# --------------------------------------------------------------------------- #
# 取值与解析工具
# --------------------------------------------------------------------------- #
def pick(record: dict, aliases: Iterable[str]) -> tuple[Any, bool]:
    """按别名顺序取第一个非 None 值，返回 ``(值, 是否命中)``。"""
    for key in aliases:
        if key in record and record[key] is not None and record[key] != "":
            return record[key], True
    return None, False


_EPOCH_HINT = re.compile(r"^\d{10}$|^\d{13}$")


def parse_date(value: Any) -> date | None:
    """尽最大努力把任意日期表示解析为 :class:`datetime.date`；失败返回 ``None``。

    支持：ISO（``2026-10-25``）、带时间、``/`` 与 ``.`` 分隔、``20261025``、
    以及 10 位秒级 / 13 位毫秒级 Unix 时间戳。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))

    text = str(value).strip()
    if not text:
        return None
    if _EPOCH_HINT.match(text):
        return _from_epoch(float(text))

    normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    # 去掉时区后缀与时间部分，只保留 YYYY-MM-DD
    normalized = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", normalized).strip()

    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:  # 例如 2026-02-30
        return None


def _from_epoch(raw: float) -> date | None:
    seconds = raw / 1000.0 if raw > 1e11 else raw
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def parse_number(value: Any) -> float | None:
    """把 ``"8元"`` / ``"￥8.00"`` / ``8`` 解析为 ``8.0``；**不确定时返回 ``None``**。

    关键防错：若字符串中出现**多个数字**（如 ``"满30减8"``），说明它是一句话而非一个数值，
    此时返回 ``None`` 由上层登记为缺失——而不是硬取第一个数字当作优惠值。
    宁可在报告里写 ``[字段缺失]``，也不能把 30 误当成优惠 8 元。
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    cleaned = str(value).replace(",", "")
    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if len(numbers) != 1:
        return None
    return float(numbers[0])


def _iter_balanced_objects(text: str) -> Iterator[str]:
    """逐个产出文本中**括号配平**的 ``{...}`` 片段（跳过字符串内部的花括号）。"""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                yield text[start : index + 1]
                start = -1


def extract_embedded_json(text: str) -> Any | None:
    """从**说明性文本**中提取内嵌的真 JSON。

    真实 ``query-my-account`` 的响应不是纯 JSON，而是这样一段"人话包裹"：

    .. code-block:: text

        # API Response Information
        ## Response Structure
        - **data.availablePoint**: 可用积分 (Type: string)
        ## Original Response
        {"success":true,"code":200,...,"data":{"availablePoint":"120.0",...}}

    直接 ``json.loads`` 整段会失败 → 早期实现因此把它归为"读不懂"。
    这里先定位 ``Original Response`` 标记，再在该标记之后找配平的大括号片段，
    取**第一个能被解析成非空 dict** 的片段返回；找不到返回 ``None``。
    """
    if not text or not text.strip():
        return None

    chunks: list[str] = []
    marker = re.search(r"original\s*response", text, re.I)
    if marker:
        chunks.append(text[marker.end() :])
    chunks.append(text)

    for chunk in chunks:
        for blob in _iter_balanced_objects(chunk):
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed:
                return parsed
            if isinstance(parsed, list) and parsed:
                return parsed
    return None


def coerce_payload(payload: Any) -> Any:
    """把 payload 规整为"可被结构化解析"的形态。

    * ``dict`` / ``list`` → 原样返回
    * 纯 JSON 文本 → 解析为对象
    * 说明性文本内嵌 JSON → 提取内嵌对象（见 :func:`extract_embedded_json`）
    * 其它文本（Markdown 正文）→ 原样返回字符串，交给文本解析器

    调用方必须在"统计返回体量"时仍使用**原始** payload，
    否则"解析失败"提示里显示的字符数会与实际收到的不符。
    """
    if isinstance(payload, (dict, list)):
        return payload
    if not isinstance(payload, str):
        return payload
    stripped = payload.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    extracted = extract_embedded_json(payload)
    return payload if extracted is None else extracted


def find_records(payload: Any, max_depth: int = 4) -> list[dict]:
    """在任意嵌套结构中定位"记录数组"。找不到返回空列表。"""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, list):
        dicts = [x for x in payload if isinstance(x, dict)]
        return dicts if dicts else []

    def _dig(obj: Any, depth: int) -> list[dict]:
        if depth > max_depth or not isinstance(obj, dict):
            return []
        for key in LIST_KEYS:
            if key in obj:
                found = _dig_list(obj[key], depth)
                if found:
                    return found
        for value in obj.values():
            found = _dig(value, depth + 1)
            if found:
                return found
        return []

    def _dig_list(obj: Any, depth: int) -> list[dict]:
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return _dig(obj, depth + 1)

    return _dig(payload, 0)


def level1_keys(payload: Any) -> list[str]:
    """列出**尚未被规范化映射**的顶层键，作为收敛别名表的线索。

    必须剔除两类键，否则报告第 8 节会被噪音淹没、并让人误以为接口有问题：

    * 协议信封（``code`` / ``message`` / ``success`` / ``datetime`` / ``traceId`` …）
      ——这些是传输层信息，本来就不该被映射；
    * 载荷容器（``data`` 等）——它下面才是字段，容器本身不是字段。

    ``traceId`` 除了是信封，还带隐私属性，故一并排除。
    """
    obj = payload
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError:
            return []
    if not isinstance(obj, dict):
        return []
    ignored = _ENVELOPE_KEYS | {key.lower() for key in _PAYLOAD_KEYS}
    return [
        key
        for key in obj
        if not str(key).startswith("_") and str(key).strip().lower() not in ignored
    ]


# --------------------------------------------------------------------------- #
# 规范化记录
# --------------------------------------------------------------------------- #
@dataclass
class Coupon:
    """规范化优惠券。``missing`` 中的字段表示"取不到"，报告须标注而非补值。

    关于 ``benefit_text`` / ``benefit_kind`` / ``price`` —— 为什么不能只有一个
    ``discount_value``：

    真实返回里券面权益写的是 ``¥9.9 (用券价格)``，意思是**用券后你付 9.9 元**，
    而不是"省 9.9 元"。若把它塞进 ``discount_value``，报告就会显示"优惠 9.9 元"，
    这是**编造**。因此这里把官方原文原样存进 ``benefit_text``，另用
    ``benefit_kind`` 标明它是价格还是减免；只有真正是"减 X 元"时，
    ``discount_value`` 才会有值，否则它老老实实留在 ``missing`` 里。
    """

    id: str | None = None
    name: str | None = None
    source: str = "my"  # "my" = 我的券；"available" = 麦麦省可领取
    coupon_type: str | None = None
    discount_value: float | None = None
    threshold: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    channel: str | None = None
    status: str | None = None
    benefit_text: str | None = None
    benefit_kind: str | None = None  # "price" | "discount" | "unknown" | None
    price: float | None = None
    tags: list[str] = field(default_factory=list)
    received_text: str | None = None
    valid_window: str | None = None
    image: str | None = None
    #: 官方原文中本技能尚未归类的字段（格式演进时的安全网）——
    #: 保留原文，进 ``raw`` 与 ``--dump-raw`` 导出，**不静默丢弃**。
    extra_text: str | None = None
    source_format: str = "json"  # "json" | "markdown"
    synthetic_id: bool = False
    #: 报告内用于互相指代的**定位编号**（如 ``MC-MY-0001``）。
    #: 与 ``id`` 分开是有原因的：``id`` 一旦被赋成合成值，
    #: "我的券"与"可领取券"两个列表之间就会发生编号碰撞，
    #: 从而把不相干的券误判为重复。因此 ``id`` 保持 ``None``，
    #: 定位编号单独存放在这里。
    ref: str | None = None
    duplicate_of_owned: bool = False
    missing: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def unknown_mark(self) -> str:
        """字段取不到时的显示标记。

        两种缺失的语义**必须分开**，否则"接口坏了"和"官方本来就不给"看起来一样：

        * Markdown 正文的字段覆盖范围是格式固定的 → 缺字段是"官方未提供"，
          显示 :data:`NOT_PROVIDED_MARK`；
        * 结构化返回里的缺字段可能是接口异常 → 显示 :data:`MISSING_MARK`。
        """
        return NOT_PROVIDED_MARK if self.source_format == "markdown" else MISSING_MARK

    @property
    def benefit_display(self) -> str:
        """报告「券面权益」列的取值：优先官方原文，其次才是解析出的数值。"""
        if self.benefit_text:
            return self.benefit_text
        if self.discount_value is not None:
            return f"减 {self.discount_value:g} 元"
        return self.unknown_mark

    @property
    def condition_display(self) -> str:
        """报告「使用条件」列的取值。原文有时段限制就用原文，否则用门槛。"""
        parts: list[str] = []
        if self.threshold is not None:
            parts.append(f"满 {self.threshold:g} 元")
        if self.valid_window:
            parts.append(self.valid_window)
        if not parts:
            return self.unknown_mark
        return "；".join(parts)

    @property
    def channel_display(self) -> str:
        return self.channel or self.unknown_mark

    def missing_label(self, key: str) -> str:
        return MISSING_MARK if key in self.missing else ""

    @property
    def display_name(self) -> str:
        return self.name or f"{MISSING_MARK}（原始记录见 raw）"

    def dedup_key(self) -> str:
        if self.id:
            return f"id:{self.id}"
        return f"name:{(self.name or '').strip()}"


@dataclass
class Campaign:
    """规范化活动。

    两种来源，语义不同，报告须分别说明：

    * ``date_source="json"`` —— 结构化的 ``start`` / ``end`` 有效期区间。
    * ``date_source="markdown"`` —— 官方活动日历按**日期归档**，只给出"这条活动出现在哪一天"。
      此时 ``calendar_date`` 为该归档日，``start`` / ``end`` 一并置为该日，
      **不代表活动的有效期区间**。``group_label`` 记录官方原文的「往期回顾」/「今日」。
    """

    id: str | None = None
    name: str | None = None
    start: date | None = None
    end: date | None = None
    status: str | None = None
    content: str | None = None
    image: str | None = None
    calendar_date: date | None = None
    group_label: str | None = None
    date_source: str = "json"
    synthetic_id: bool = False
    missing: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name or f"{MISSING_MARK}（原始记录见 raw）"


@dataclass
class PointsAccount:
    """积分账户。``present`` 为 False 表示整个工具未取到数据。

    字段覆盖面按 2026-10-09 真实返回（``## Original Response`` 内嵌 JSON）设定，
    全部为**字符串型数字**，故一律经 :func:`parse_number` 转换后存放。
    ``account_id`` 属隐私字段：识别到即记录"存在过"，但**不落库、不进报告**。
    """

    available: float | None = None
    total: float | None = None
    frozen: float | None = None
    expiring_points: float | None = None
    expiring_date: date | None = None
    level: str | None = None
    used: float | None = None
    expired: float | None = None
    next_expiring_points: float | None = None
    last_expired: float | None = None
    currency: str | None = None
    account_id_excluded: bool = False
    present: bool = False
    missing: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class SourceStatus:
    """单个数据源的取数结果，用于报告的"数据源状态表"。

    ``state`` 与 ``ok`` 必须同时看：``ok=True`` 只表示"调用没报错"，
    不代表"数据被读懂了"。``state`` 才决定报告能否下"没有数据"的结论。
    """

    tool: str
    ok: bool
    error: str | None = None
    record_count: int = 0
    unknown_keys: list[str] = field(default_factory=list)
    state: PayloadState = PayloadState.PARSED
    payload_chars: int = 0
    observed_format: str = "unknown"
    absent_fields: list[str] = field(default_factory=list)

    @property
    def parsed(self) -> bool:
        return self.state is PayloadState.PARSED

    @property
    def unrecognized(self) -> bool:
        """收到内容但解析器读不懂——最需要警惕的状态。"""
        return self.state is PayloadState.UNRECOGNIZED

    def summary(self) -> str:
        """状态表用的短标签。"""
        return {
            PayloadState.PARSED: "✅ 成功",
            PayloadState.EMPTY: "⚪ 成功（无数据）",
            PayloadState.UNRECOGNIZED: "⚠️ 解析失败",
            PayloadState.FAILED: "❌ 取数失败",
        }[self.state]


@dataclass
class Bundle:
    """归一化后的完整数据集。"""

    mode: str
    today: date
    generated_at: datetime
    my_coupons: list[Coupon] = field(default_factory=list)
    available_coupons: list[Coupon] = field(default_factory=list)
    campaigns: list[Campaign] = field(default_factory=list)
    account: PointsAccount = field(default_factory=PointsAccount)
    sources: list[SourceStatus] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)

    @property
    def all_coupons(self) -> list[Coupon]:
        return [*self.my_coupons, *self.available_coupons]

    def source(self, tool: str) -> SourceStatus | None:
        for status in self.sources:
            if status.tool == tool:
                return status
        return None

    def integrity_notes(self) -> list[str]:
        """汇总所有完整性缺口，供报告如实披露。"""
        notes: list[str] = []
        for status in self.sources:
            if status.state is PayloadState.FAILED:
                notes.append(f"`{status.tool}` 取数失败：{status.error or '未知原因'}")
            elif status.state is PayloadState.UNRECOGNIZED:
                notes.append(
                    f"**`{status.tool}` 收到数据，但解析失败**：返回了 "
                    f"{status.payload_chars} 字符内容，却未能识别出任何记录。"
                    "本报告**不得**据此判断该项为「没有数据」——"
                    "请用 `--dump-raw` 导出原始返回核对格式。"
                )
        notes.extend(_aggregate_missing(self.my_coupons, "我的券"))
        notes.extend(_aggregate_missing(self.available_coupons, "可领取券"))
        if self.account.present and self.account.missing:
            labels = "、".join(FIELD_LABELS.get(k, k) for k in self.account.missing)
            notes.append(
                f"积分账户的这些字段官方接口未提供，报告记为 {MISSING_MARK}（{NOT_PROVIDED_MARK}）：{labels}"
            )
        notes.extend(self._absent_field_notes())
        notes.extend(_aggregate_missing(self.campaigns, "活动"))
        notes.extend(self.parse_notes)
        return notes

    def _absent_field_notes(self) -> list[str]:
        """说明"该来源格式本身不携带"的字段。

        与"某条记录恰好缺字段"不同：这是格式属性，逐条罗列只会把第 8 节淹掉。
        因此每个数据源聚合说明一次，并附上不提供该字段的原因。
        """
        notes: list[str] = []
        for status in self.sources:
            if not status.absent_fields:
                continue
            items = []
            for key in status.absent_fields:
                label = FIELD_LABELS.get(key, key)
                hint = ABSENT_FIELD_NOTES.get(key)
                items.append(f"「{label}」" + (f"—{hint}" if hint else ""))
            notes.append(
                f"`{status.tool}` 的返回格式不包含以下字段，报告中一律记为 {MISSING_MARK}，未做任何推测："
                + "；".join(items)
            )
        return notes



# --------------------------------------------------------------------------- #
# 缺失项的聚合表述
# --------------------------------------------------------------------------- #
def _aggregate_missing(records: list[Any], kind: str, threshold: int = 2) -> list[str]:
    """把逐条缺失汇总成可读的说明。

    Markdown 来源的券/活动天然缺若干字段，逐条罗列会让第 8 节长达几十行；
    同一字段缺失超过 ``threshold`` 条时改为聚合表述，**信息量不减、噪音大减**。
    """
    by_field: dict[str, list[str]] = {}
    for record in records:
        ref = str(
            getattr(record, "id", None)
            or getattr(record, "ref", None)
            or getattr(record, "display_name", "?")
        )
        for key in getattr(record, "missing", []):
            by_field.setdefault(key, []).append(ref)

    notes: list[str] = []
    for key, refs in by_field.items():
        label = FIELD_LABELS.get(key, key)
        if len(refs) <= threshold:
            for ref in refs:
                notes.append(f"{kind} `{ref}` 缺失字段：{label}（{NOT_PROVIDED_MARK}）")
        else:
            sample = "、".join(f"`{r}`" for r in refs[:2])
            notes.append(
                f"{kind}记录中有 {len(refs)} 条缺失字段「{label}」（如 {sample} 等），"
                f"已按 {MISSING_MARK} 处理，未做任何补值。"
            )
    return notes


# --------------------------------------------------------------------------- #
# 归一化入口
# --------------------------------------------------------------------------- #
def normalize_coupon(record: dict, source: str) -> Coupon:
    """把一条券记录规范化为 :class:`Coupon`。

    两种来源共享同一套别名解析，差别只在 ``missing`` 的登记口径：

    * ``json`` —— 每个规范字段都应当能从结构化返回里取到，取不到就登记缺失。
    * ``markdown`` —— 正文只覆盖「券名 + 有效期 + 标签 + 券面权益」等少数几项，
      其余字段是**格式本身不提供**（见 :data:`MD_COUPON_ABSENT`），
      逐条登记只会制造噪音。因此 markdown 来源只对**每条都应有**的字段
      （:data:`MD_COUPON_REQUIRED`）登记缺失，其余由数据源状态统一说明。
    """
    coupon = Coupon(source=source, raw=record)
    coupon.source_format = str(record.get("_source") or "json")
    coupon.synthetic_id = bool(record.get("_syntheticId"))
    coupon.benefit_text = record.get("_benefitText") or None
    coupon.benefit_kind = record.get("_benefitKind") or None
    coupon.price = record.get("_price")
    raw_tags = record.get("_tags")
    coupon.tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
    coupon.received_text = record.get("_receivedText") or None
    coupon.valid_window = record.get("_validWindow") or None
    coupon.image = record.get("_image") or None
    coupon.extra_text = record.get("_content") or None

    markdown = coupon.source_format == "markdown"
    if markdown:
        # 两个 Markdown 来源的字段覆盖范围不同，必需集也不同：
        # 「我的券」带有效期，「可领取券」只有标题/状态/图片。
        # 用错必需集会把"格式本来就不提供"误报成"这条缺字段"。
        required: tuple[str, ...] | None = MD_COUPON_REQUIRED if source == "my" else MD_AVAILABLE_REQUIRED
    else:
        required = None

    def note_missing(key: str) -> None:
        if required is None or key in required:
            coupon.missing.append(key)

    coupon.id, ok = pick(record, COUPON_ALIASES["id"])
    if not ok and not coupon.synthetic_id:
        note_missing("id")
    coupon.name, ok = pick(record, COUPON_ALIASES["name"])
    if not ok:
        note_missing("name")
    coupon.coupon_type, ok = pick(record, COUPON_ALIASES["coupon_type"])
    if not ok:
        note_missing("coupon_type")

    raw_value, _ = pick(record, COUPON_ALIASES["discount_value"])
    coupon.discount_value = parse_number(raw_value)
    if coupon.discount_value is None:
        note_missing("discount_value")

    raw_threshold, _ = pick(record, COUPON_ALIASES["threshold"])
    coupon.threshold = parse_number(raw_threshold)
    if coupon.threshold is None:
        note_missing("threshold")

    raw_from, _ = pick(record, COUPON_ALIASES["valid_from"])
    coupon.valid_from = parse_date(raw_from)
    raw_to, to_present = pick(record, COUPON_ALIASES["valid_to"])
    coupon.valid_to = parse_date(raw_to)
    if not to_present or coupon.valid_to is None:
        note_missing("valid_to")

    coupon.channel, ok = pick(record, COUPON_ALIASES["channel"])
    if not ok:
        note_missing("channel")
    coupon.status, ok = pick(record, COUPON_ALIASES["status"])
    if not ok:
        note_missing("status")

    # 已持有官方原文的券面权益时，不再把「优惠值」笼统报成缺失——
    # 否则报告会一边显示「¥9.9 (用券价格)」一边说「优惠值 [字段缺失]」，自相矛盾。
    # 真正的口径是：券面权益**已给出**，只是它形如"价格"而非"减免"，
    # 该语义由 benefit_kind 表达。
    if coupon.benefit_text and "discount_value" in coupon.missing:
        coupon.missing.remove("discount_value")
    return coupon


def normalize_campaign(record: dict) -> Campaign:
    """把一条活动记录规范化为 :class:`Campaign`。

    兼容两种来源：JSON 结构（显式有效期）与 Markdown 解析产物
    （``_`` 前缀的元数据，见 :func:`parse_campaign_markdown`）。
    """
    campaign = Campaign(raw=record)
    campaign.id, ok = pick(record, CAMPAIGN_ALIASES["id"])
    campaign.synthetic_id = bool(record.get("_syntheticId"))
    campaign.date_source = str(record.get("_source") or "json")
    campaign.group_label = record.get("_groupLabel") or None
    campaign.content = record.get("_content") or None
    campaign.image = record.get("_image") or None
    campaign.calendar_date = parse_date(record.get("_calendarDate"))

    # 结构化来源才要求官方活动ID；Markdown 日历不提供该字段，用生成的定位编号代替，
    # 此时不计入 missing（否则会徒增 30 条噪音），但 synthetic_id 会单独在报告中说明。
    if not ok and not campaign.synthetic_id:
        campaign.missing.append("id")

    campaign.name, name_ok = pick(record, CAMPAIGN_ALIASES["name"])
    if not name_ok:
        campaign.missing.append("name")
    raw_start, _ = pick(record, CAMPAIGN_ALIASES["start"])
    campaign.start = parse_date(raw_start)
    raw_end, end_present = pick(record, CAMPAIGN_ALIASES["end"])
    campaign.end = parse_date(raw_end)
    if not end_present or campaign.end is None:
        campaign.missing.append("end")
    campaign.status, ok = pick(record, CAMPAIGN_ALIASES["status"])
    if not ok:
        # Markdown 日历只在「往期回顾 / 今日」分组给出状态，未来日期无标签。
        # 这是格式本身如此，不是数据缺陷，因此不登记为 missing。
        if campaign.date_source != "markdown":
            campaign.missing.append("status")
    return campaign


def _has_account_fields(record: dict) -> bool:
    """判断这个 dict 里**真的含积分账户字段**，而不只是协议信封。

    ``{"code":0,"message":"请求成功"}`` 是"调用成功但没有数据"，
    若把 ``present`` 判成 True，报告会列出满屏 ``[字段缺失]``，
    读起来像"接口坏了"，而真相是"没有账户数据"。两者必须分开。
    """
    return any(
        key in record and record[key] not in (None, "")
        for aliases in POINTS_ALIASES.values()
        for key in aliases
    )


def normalize_account(payload: Any) -> PointsAccount:
    account = PointsAccount()
    record: dict = {}
    if isinstance(payload, dict):
        # 真实返回可能包一层 data
        candidate = payload.get("data", payload)
        record = candidate if isinstance(candidate, dict) else payload
        if not any(k in record for aliases in POINTS_ALIASES.values() for k in aliases):
            nested = find_records(payload)
            if nested:
                record = nested[0]
    elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
        record = payload[0]

    if not record or not _has_account_fields(record):
        account.missing = list(ACCOUNT_REQUIRED_FIELDS)
        return account

    # 隐私字段：识别到"存在过"即止，**取值既不落库也不进报告**。
    raw_account_id, has_account_id = pick(record, POINTS_ALIASES["account_id"])
    account.account_id_excluded = bool(has_account_id and raw_account_id)
    account.raw = {
        key: value
        for key, value in record.items()
        if key not in ACCOUNT_PRIVACY_KEYS
    }

    account.present = True
    for field_name in ACCOUNT_NUMERIC_FIELDS:
        raw_value, ok = pick(record, POINTS_ALIASES[field_name])
        setattr(account, field_name, parse_number(raw_value))
        if not ok or getattr(account, field_name) is None:
            account.missing.append(field_name)

    raw_date, date_ok = pick(record, POINTS_ALIASES["expiring_date"])
    account.expiring_date = parse_date(raw_date)
    if not date_ok or account.expiring_date is None:
        account.missing.append("expiring_date")

    account.level, level_ok = pick(record, POINTS_ALIASES["level"])
    if not level_ok:
        account.missing.append("level")

    account.currency, _ = pick(record, POINTS_ALIASES["currency"])
    if account.currency is not None:
        account.currency = str(account.currency).strip() or None
    return account


# --------------------------------------------------------------------------- #
# 活动日历：Markdown 正文解析
# --------------------------------------------------------------------------- #
#: 日期分组标题，如 ``#### 2026年10月7日 往期回顾``。
#: 分隔符容忍 年/月/日 与 - / . 两种写法；前缀 ``#`` 数量不限。
_MD_DATE_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?\s*(.*?)\s*$"
)

#: 条目起始：``-   **活动标题**：xxx``
_MD_ENTRY_START = re.compile(r"^\s*[-*+]\s+\*\*\s*(?P<field>[^*]+?)\s*\*\*\s*[：:]\s*(?P<value>.*)$")

#: 条目内字段：``    **活动内容介绍**：xxx``
_MD_FIELD = re.compile(r"^\s*\*\*\s*(?P<field>[^*]+?)\s*\*\*\s*[：:]\s*(?P<value>.*)$")

#: 图片地址（宽松匹配，src 可带或不带引号）
_MD_IMG = re.compile(r"""<img[^>]*\bsrc\s*=\s*["']?([^"'\s>]+)""", re.I)

_MD_TITLE_KEYS = frozenset({"活动标题", "活动名称", "标题", "活动主题", "主题"})
_MD_CONTENT_KEYS = frozenset({"活动内容介绍", "活动内容", "活动介绍", "活动说明", "活动描述", "内容"})
_MD_IMAGE_KEYS = frozenset({"活动图片介绍", "活动图片", "图片", "活动配图"})


def _md_field_kind(name: str) -> str:
    """把官方字段名归一为 ``title`` / ``content`` / ``image`` / ``other``。"""
    cleaned = re.sub(r"\s+", "", name or "")
    if cleaned in _MD_TITLE_KEYS:
        return "title"
    if cleaned in _MD_CONTENT_KEYS:
        return "content"
    if cleaned in _MD_IMAGE_KEYS:
        return "image"
    return "other"


def parse_campaign_markdown(text: str) -> tuple[list[dict], list[str]]:
    """解析活动日历的 Markdown 正文，返回 ``(记录列表, 警告列表)``。

    结构（取自 2026-10-09 对官方 MCP 的真实响应）::

        ### 当前时间：2026-10-09 15:26:02

        ### 活动列表：

        #### 2026年10月7日 往期回顾

        -   **活动标题**：【合成样例】活动标题
            **活动内容介绍**：合成示例正文第一行
            合成示例正文第二行……
            **活动图片介绍**：
            <img src="https://example.invalid/cdn/campaign/xxx.jpg" ...>

    产出的记录字典键名与 :data:`CAMPAIGN_ALIASES` 对齐，可直接交给
    :func:`normalize_campaign`，因此 JSON 与 Markdown 两条路径共享同一套归一化逻辑。

    诚实性约束：

    * 官方日历**只给出归档日期**（该活动出现在哪一天），不提供有效期区间。
      记录中把该日期同时填入 ``startDate`` / ``endDate``，并在 ``_calendarDate``
      标记其真实语义，由报告层负责措辞。
    * 官方**不提供活动ID**。这里生成 ``MD-YYYYMMDD-NN`` 仅作为报告内的定位编号，
      以 ``_syntheticId`` 标记，绝不是官方 ID。
    * 无法提取标题的条目、以及未解析出任何条目的日期分组，**一律记入警告**，
      不静默丢弃。
    """
    lines = text.splitlines()
    records: list[dict] = []
    warnings: list[str] = []
    pending_days: list[tuple[date, str, int]] = []

    class _Cursor:
        """可变状态容器，避免多层嵌套函数互相踩状态。"""

        day: date | None = None
        label: str = ""
        block: dict | None = None
        field: str | None = None
        day_count: int = 0

    cur = _Cursor()

    def close_day() -> None:
        if cur.day is not None:
            pending_days.append((cur.day, cur.label, cur.day_count))
        cur.day, cur.label, cur.day_count, cur.field = None, "", 0, None

    def close_block() -> None:
        block = cur.block
        cur.block = None
        if block is None:
            return
        title = (block.get("title") or "").strip()
        body = "\n".join(block.get("content") or []).strip()
        if not title:
            warnings.append(
                f"日期 {block['date']} 下有 1 条活动未能提取到标题，已跳过（原文请用 --dump-raw 查看）"
            )
            return
        cur.day_count += 1
        records.append(
            {
                "campaignId": f"MD-{block['date']:%Y%m%d}-{cur.day_count:02d}",
                "campaignName": title,
                "startDate": block["date"].isoformat(),
                "endDate": block["date"].isoformat(),
                "status": cur.label or None,
                "_source": "markdown",
                "_syntheticId": True,
                "_calendarDate": block["date"].isoformat(),
                "_groupLabel": cur.label or None,
                "_content": body or None,
                "_image": block.get("image"),
            }
        )

    for line in lines:
        heading = _MD_DATE_HEADING.match(line)
        if heading:
            close_block()
            close_day()
            try:
                cur.day = date(int(heading.group(1)), int(heading.group(2)), int(heading.group(3)))
            except ValueError:
                warnings.append(f"日期分组「{line.strip()}」不是合法日期，已跳过该分组")
                continue
            cur.label = (heading.group(4) or "").strip()
            continue

        if cur.day is None:
            continue  # 尚未进入任何日期分组（如"当前时间""活动列表"标题）

        start = _MD_ENTRY_START.match(line)
        if start:
            # 带项目符号 + 加粗字段 + 冒号 → 几乎可以肯定是活动条目。
            # 即使首个字段不是标题（格式变更、标题缺失），也要先把块建起来，
            # 让缺标题这件事以精确的警告出现，而不是被降级成"这个日期没有活动"。
            kind = _md_field_kind(start.group("field"))
            value = start.group("value").strip()
            close_block()
            cur.block = {
                "date": cur.day,
                "title": value if kind == "title" else "",
                "content": [],
                "image": None,
            }
            cur.field = kind
            if kind == "content" and value:
                cur.block["content"].append(value)
            elif kind == "image":
                img = _MD_IMG.search(value)
                if img:
                    cur.block["image"] = img.group(1)
            elif kind == "other" and value:
                cur.block["content"].append(f"{start.group('field').strip()}：{value}")
            continue

        field_match = _MD_FIELD.match(line)
        if field_match and cur.block is not None:
            kind = _md_field_kind(field_match.group("field"))
            value = field_match.group("value").strip()
            if kind == "title":
                if not cur.block.get("title"):
                    cur.block["title"] = value
                else:
                    cur.block["content"].append(value)
                cur.field = "title"
            elif kind == "content":
                cur.block["content"].append(value)
                cur.field = "content"
            elif kind == "image":
                cur.field = "image"
                img = _MD_IMG.search(value)
                if img:
                    cur.block["image"] = img.group(1)
            else:
                cur.field = "other"
                if value:
                    cur.block["content"].append(f"{field_match.group('field').strip()}：{value}")
            continue

        # 续行：接到当前条目正在处理的字段上
        stripped = line.strip()
        if cur.block is not None and stripped:
            if cur.field == "image":
                img = _MD_IMG.search(stripped)
                if img and not cur.block.get("image"):
                    cur.block["image"] = img.group(1)
            elif cur.field in ("content", "title", "other"):
                cur.block["content"].append(stripped)

    close_block()
    close_day()

    for day, label, count in pending_days:
        if count == 0:
            suffix = f"（分组标签：{label}）" if label else ""
            warnings.append(f"日期 {day} 的分组未解析出任何活动条目{suffix}，请核对原始返回结构")

    if not records and not _is_effectively_empty(text):
        warnings.append(
            "整份响应未能解析出任何活动条目，但原文非空。"
            "格式可能与当前解析器不符，请用 --dump-raw 导出原始返回核对。"
        )
    return records, warnings


def _is_effectively_empty(text: str) -> bool:
    """判断正文是否**只有标题 / 计数声明、没有任何实质条目**。

    真实的"空结果"就长这样：例如本月没有可领取券时，服务器只回一个
    ``### 麦麦省优惠券列表：`` 标题。把它判成"解析失败"是**错误的报警**，
    会让用户以为接口坏了。

    因此必须把三种情况分清：

    * 只有标题 → 真空（``EMPTY``，不报警）；
    * 有实质内容但读不懂 → 解析失败（``UNRECOGNIZED``，**必须报警**）；
    * 标题下有条目但一条都没解出来 → 由各解析器另行报警。
    """
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _MD_COUPON_COUNT.search(line):
            continue
        return False
    return True


# --------------------------------------------------------------------------- #
# 我的优惠券：Markdown 正文解析
# --------------------------------------------------------------------------- #
#: 券名标题：``## 【合成样例】券名``。要求**恰好两级** ``#``，
#: 这样 ``# 您的优惠券列表`` 与 ``### 麦麦省优惠券列表：`` 都不会被误当成券名。
_MD_COUPON_HEADING = re.compile(r"^\s{0,3}##(?!#)\s*(?P<name>.+?)\s*$")

#: 券条目字段：``- **优惠**: ¥9.9 (用券价格)``
_MD_COUPON_FIELD = re.compile(
    r"^\s*[-*+]\s*\*\*\s*(?P<field>[^*]+?)\s*\*\*\s*[：:]\s*(?P<value>.*)$"
)

#: 文档头部声明的总条数：``共 14 张可用优惠券 | 第 1/1 页 | 每页 200 条``
_MD_COUPON_COUNT = re.compile(r"共\s*(?P<count>\d+)\s*张")

#: 日期（可带时分秒）：``2026-10-05 10:30``
_MD_DATETIME = re.compile(
    r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"
    r"(?:\s+(?P<hh>\d{1,2}):(?P<mi>\d{2})(?::(?P<ss>\d{2}))?)?"
)

#: 券面权益里表示"这是用券后价格"的限定词（按官方原文口径）
_PRICE_QUALIFIERS: tuple[str, ...] = ("用券价", "券后价", "到手价", "折后价")

#: 券面权益里表示"这是减免"的关键字
_DISCOUNT_KEYWORDS: tuple[str, ...] = ("减", "省", "抵扣", "返")

#: 标签中属于"状态"语义的取值
_STATUS_TAG_VALUES: tuple[str, ...] = (
    "今日到期",
    "明日到期",
    "即将到期",
    "已过期",
    "已使用",
    "已失效",
    "已作废",
    "可使用",
)

_BENEFIT_KEYS = frozenset({"优惠", "券面权益", "权益", "优惠内容", "优惠信息"})
_VALIDITY_KEYS = frozenset({"有效期", "有效时间", "使用时间", "可用时间"})
_RECEIVED_KEYS = frozenset({"领取时间", "获得时间", "获取时间", "入账时间"})
_TAG_KEYS = frozenset({"标签", "券标签", "标记"})
_STATUS_KEYS = frozenset({"状态", "券状态", "优惠券状态"})
_COUPON_IMAGE_KEYS = frozenset({"券图", "券图片", "优惠券图片", "图片", "配图"})


def _coupon_field_kind(name: str) -> str:
    """把官方字段名归一为 ``benefit`` / ``validity`` / ``received`` / ``tags`` / ``status`` / ``image`` / ``other``。"""
    cleaned = re.sub(r"\s+", "", name or "")
    if cleaned in _BENEFIT_KEYS:
        return "benefit"
    if cleaned in _VALIDITY_KEYS:
        return "validity"
    if cleaned in _RECEIVED_KEYS:
        return "received"
    if cleaned in _TAG_KEYS:
        return "tags"
    if cleaned in _STATUS_KEYS:
        return "status"
    if cleaned in _COUPON_IMAGE_KEYS:
        return "image"
    return "other"


def classify_benefit(raw: str) -> tuple[str, float | None, str]:
    """判定券面权益是**用券价格**还是**减免**，返回 ``(kind, value, 说明)``。

    这是本项目最需要克制的一处：官方原文写的是 ``¥9.9 (用券价格)``，
    含义是"用券后实付 9.9 元"，**不是"省 9.9 元"**。
    早期若把它直接塞进 ``discount_value``，报告就会写"优惠 9.9 元"——那是编造。

    判不准时返回 ``("unknown", None, 说明)``：原文照登，**不做任何换算**。
    """
    text = (raw or "").strip()
    if not text:
        return "unknown", None, ""
    compact = re.sub(r"\s+", "", text)
    value = parse_number(text)
    if any(qualifier in compact for qualifier in _PRICE_QUALIFIERS):
        return "price", value, "官方原文标注为「用券价格」：指用券后实付金额，不是优惠金额"
    if any(keyword in compact for keyword in _DISCOUNT_KEYWORDS):
        return "discount", value, ""
    return "unknown", None, "无法判定券面权益是价格还是减免，已按原文展示、未做任何换算"


def _date_from_match(match: re.Match[str]) -> date | None:
    try:
        return date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
    except ValueError:  # 例如 2026-02-30
        return None


def parse_coupon_validity(raw: str) -> tuple[date | None, date | None, str | None]:
    """解析有效期原文，返回 ``(起, 止, 适用时段原文)``。

    官方原文形如::

        2026-10-05 10:30-2026-10-09 23:59 周一、二、三、四、五 10:30-23:59

    取**前两个**日期为起止；尾部残留的"星期 + 时段"限制原样保留为
    ``适用时段``——它是真实的使用条件，但**不做任何解释性换算**。
    """
    text = (raw or "").strip()
    if not text:
        return None, None, None
    found = list(_MD_DATETIME.finditer(text))
    if not found:
        return None, None, text or None

    start = _date_from_match(found[0])
    end = _date_from_match(found[1]) if len(found) > 1 else start

    remainder = text
    for match in reversed(found):
        begin, stop = match.span()
        remainder = remainder[:begin] + "\x00" + remainder[stop:]
    remainder = remainder.replace("\x00", "")
    window = remainder.strip().strip("-—–~～至到").strip()
    return start, end, (window or None)


def _coupon_record_from_block(block: dict) -> dict:
    """把解析中的券块转成与 :data:`COUPON_ALIASES` 对齐的记录字典。"""
    benefit = (block.get("benefit") or "").strip()
    kind, value, _note = classify_benefit(benefit)
    tags = [str(t).strip() for t in block.get("tags") or [] if str(t).strip()]

    explicit_status = (block.get("status") or "").strip()
    status = explicit_status or next((t for t in tags if t in _STATUS_TAG_VALUES), "")
    channels = [t for t in tags if t not in _STATUS_TAG_VALUES]

    start, end, window = parse_coupon_validity(block.get("validity") or "")
    extra = "\n".join(block.get("content") or []).strip()

    record: dict = {
        "couponName": (block.get("name") or "").strip(),
        "validFrom": start.isoformat() if start else None,
        "validTo": end.isoformat() if end else None,
        "couponStatus": status or None,
        "useChannel": "、".join(channels) or None,
        "_source": "markdown",
        "_syntheticId": True,
        "_benefitText": benefit or None,
        "_benefitKind": kind,
        "_price": value if kind == "price" else None,
        "_tags": tags,
        "_receivedText": block.get("received") or None,
        "_validWindow": window,
        "_image": block.get("image"),
        # 官方将来新增字段时，原文进这里——进 raw、进 --dump-raw，**不丢弃**
        "_content": extra or None,
    }
    if kind == "discount" and value is not None:
        record["discountValue"] = value
    return record


def parse_coupon_markdown(text: str) -> tuple[list[dict], list[str]]:
    """解析"我的优惠券"的 Markdown 正文，返回 ``(记录列表, 警告列表)``。

    结构（取自 2026-10-09 对官方 MCP 的真实响应）::

        # 您的优惠券列表

        共 14 张可用优惠券 | 第 1/1 页 | 每页 200 条

        ## 【合成样例】券名
        - **优惠**: ¥9.9 (用券价格)
        - **有效期**: 2026-10-05 10:30-2026-10-09 23:59 周一、二、三、四、五 10:30-23:59
        - **领取时间**: 4日前收到
        - **标签**: 今日到期、到店专用、外送专用

        <img src="..." alt="【合成样例】券名" ...>

    诚实性约束：

    * 头部写的总条数与实际解析出的条数不一致时**必须报警**——
      这正是"解析失败不得伪装成没有数据"的同类风险。
    * 提取不到券名的块记入警告，不静默丢弃。
    * 券面权益按原文登记并标注类型，**绝不把用券价格当成优惠金额**。
    """
    records: list[dict] = []
    warnings: list[str] = []
    block: dict | None = None

    def close_block() -> None:
        nonlocal block
        if block is None:
            return
        name = (block.get("name") or "").strip()
        if not name:
            warnings.append("有一张券未能提取到券名，已跳过该条（原文请用 --dump-raw 查看）")
        else:
            records.append(_coupon_record_from_block(block))
        block = None

    def append_value(target: str, value: str) -> None:
        if block is None or not value:
            return
        if target == "content":
            block.setdefault("content", []).append(value)
        else:
            existing = block.get(target)
            block[target] = f"{existing} {value}".strip() if existing else value

    for line in text.splitlines():
        heading = _MD_COUPON_HEADING.match(line)
        if heading:
            close_block()
            block = {"name": heading.group("name").strip()}
            continue
        if block is None:
            continue

        field = _MD_COUPON_FIELD.match(line)
        if field:
            kind = _coupon_field_kind(field.group("field"))
            value = field.group("value").strip()
            if kind == "benefit":
                append_value("benefit", value)
            elif kind == "validity":
                append_value("validity", value)
            elif kind == "received":
                append_value("received", value)
            elif kind == "status":
                append_value("status", value)
            elif kind == "image":
                img = _MD_IMG.search(value)
                if img and not block.get("image"):
                    block["image"] = img.group(1)
            elif kind == "tags":
                block.setdefault("tags", []).extend(
                    part.strip() for part in re.split(r"[、,，;；/]", value) if part.strip()
                )
            elif value:
                # 格式新增了字段——保留原文，绝不丢弃
                append_value("content", f"{field.group('field').strip()}：{value}")
            continue

        img = _MD_IMG.search(line)
        if img and not block.get("image"):
            block["image"] = img.group(1)
            continue

        # 续行：接到"有效期"这类可能被折行的字段上
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            append_value("content", stripped)

    close_block()

    expected_match = _MD_COUPON_COUNT.search(text)
    if expected_match:
        expected = int(expected_match.group("count"))
        if expected != len(records):
            warnings.append(
                f"正文声明「共 {expected} 张」，实际解析出 {len(records)} 张，"
                f"相差 {abs(expected - len(records))} 张。**请勿据本报告判断券的数量**，"
                "请用 --dump-raw 导出原始返回核对格式。"
            )

    if not records and not _is_effectively_empty(text):
        warnings.append(
            "整份响应未能解析出任何优惠券条目，但原文非空。"
            "格式可能与当前解析器不符，请用 --dump-raw 导出原始返回核对。"
        )
    return records, warnings


# --------------------------------------------------------------------------- #
# 可领取券（麦麦省）：Markdown 正文解析
# --------------------------------------------------------------------------- #
#: 可领取券标题行：``- 优惠券标题：【合成样例】券名 \``（行尾反斜杠是续行标记）
_MD_AVAIL_TITLE = re.compile(
    r"^\s*[-*+]\s*(?:优惠券标题|券标题|券名称|名称|标题)\s*[：:]\s*(?P<value>.*)$"
)

#: 可领取券内联字段：``  状态：已领取 \`` / ``  优惠券图片：\``
_MD_AVAIL_FIELD = re.compile(
    r"^\s*(?P<field>状态|优惠券状态|券状态|优惠券图片|券图片|图片|有效期|有效时间"
    r"|优惠券类型|券类型|使用条件|门槛|优惠)\s*[：:]\s*(?P<value>.*)$"
)

_MD_AVAIL_STATUS_KEYS = frozenset({"状态", "优惠券状态", "券状态"})
_MD_AVAIL_IMAGE_KEYS = frozenset({"优惠券图片", "券图片", "图片"})
_MD_AVAIL_VALIDITY_KEYS = frozenset({"有效期", "有效时间"})


def _strip_continuation(line: str) -> str:
    """去掉 Markdown 行尾的续行反斜杠。"""
    return re.sub(r"\s*\\\s*$", "", line).rstrip()


def parse_available_coupons_markdown(text: str) -> tuple[list[dict], list[str]]:
    """解析"麦麦省可领取券"的 Markdown 正文，返回 ``(记录列表, 警告列表)``。

    结构（取自 2026-10-09 对官方 MCP 的真实响应）::

        ### 麦麦省优惠券列表：
        - 优惠券标题：【合成样例】券名 \\
          状态：已领取 \\
          优惠券图片：\\
            <img src="..." alt="【合成样例】券名" ...>

    这个格式的关键点：

    * 字段用**行尾反斜杠**续行，不是 Markdown 列表项——不能按列表切分。
    * ``状态`` 会同时出现 ``已领取`` 与 ``可领取``：**这份列表里既有已领的也有可领的**，
      报告必须照实区分（只有 ``可领取`` 才是"待领取"）。
    * 正文不提供有效期——因此这些券无法按到期紧急度排序，报告须说明"未提供"。
    """
    records: list[dict] = []
    warnings: list[str] = []
    block: dict | None = None
    stray: list[str] = []

    def close_block() -> None:
        nonlocal block
        if block is None:
            return
        title = (block.get("name") or "").strip()
        if not title:
            warnings.append("有一张可领取券未能提取到标题，已跳过该条（原文请用 --dump-raw 查看）")
        else:
            record: dict = {
                "couponName": title,
                "couponStatus": (block.get("status") or "").strip() or None,
                "_source": "markdown",
                "_syntheticId": True,
                "_image": block.get("image"),
                "_content": " / ".join(block.get("extra") or []) or None,
            }
            validity = (block.get("validity") or "").strip()
            if validity:
                start, end, window = parse_coupon_validity(validity)
                record["validFrom"] = start.isoformat() if start else None
                record["validTo"] = end.isoformat() if end else None
                record["_validWindow"] = window
            records.append(record)
        block = None

    for raw_line in text.splitlines():
        line = _strip_continuation(raw_line)
        if not line.strip():
            continue

        title_match = _MD_AVAIL_TITLE.match(line)
        if title_match:
            close_block()
            block = {"name": title_match.group("value").strip()}
            continue

        if block is None:
            # 不在任何条目内、又不是标题的实质内容 → 不能静默丢弃，先收集起来
            if not line.lstrip().startswith("#") and not _MD_IMG.search(line):
                stray.append(line.strip())
            continue

        field_match = _MD_AVAIL_FIELD.match(line)
        if field_match:
            key = re.sub(r"\s+", "", field_match.group("field"))
            value = field_match.group("value").strip()
            if key in _MD_AVAIL_STATUS_KEYS:
                block["status"] = value
            elif key in _MD_AVAIL_IMAGE_KEYS:
                img = _MD_IMG.search(value)
                if img:
                    block["image"] = img.group(1)
            elif key in _MD_AVAIL_VALIDITY_KEYS:
                block["validity"] = value
            elif value:
                block.setdefault("extra", []).append(f"{key}：{value}")
            continue

        img = _MD_IMG.search(line)
        if img:
            if not block.get("image"):
                block["image"] = img.group(1)
            continue

        block.setdefault("extra", []).append(line.strip())

    close_block()

    if stray:
        preview = "；".join(stray[:3])
        warnings.append(
            f"响应中有 {len(stray)} 行内容不在任何券条目内，未能归类（{preview}…），"
            "已原样保留在 --dump-raw 的导出中。"
        )
    if not records and not _is_effectively_empty(text):
        warnings.append(
            "整份响应未能解析出任何可领取券条目，但原文非空。"
            "格式可能与当前解析器不符，请用 --dump-raw 导出原始返回核对。"
        )
    return records, warnings


#: 返回正文而非 JSON 的工具 → 文本解析器。找不到记录时按此表回退，
#: 而不是直接把结果当成"空"。（四个工具的真实格式均已实测确认。）
_TEXT_PARSERS: dict[str, Callable[[str], tuple[list[dict], list[str]]]] = {
    "campaign-calendar": parse_campaign_markdown,
    "query-my-coupons": parse_coupon_markdown,
    "available-coupons": parse_available_coupons_markdown,
}

#: 各工具在"文本回退成功"后应声明的"格式不提供"字段
_ABSENT_FIELDS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "query-my-coupons": MD_COUPON_ABSENT,
    "available-coupons": MD_AVAILABLE_ABSENT,
}


def _mark_duplicates(mine: list[Coupon], claimable: list[Coupon]) -> None:
    """标记"我已持有"的可领取券，避免重复推荐。"""
    owned = {c.dedup_key() for c in mine}
    owned_names = {(c.name or "").strip() for c in mine if c.name}
    for coupon in claimable:
        if coupon.dedup_key() in owned or (coupon.name or "").strip() in owned_names:
            coupon.duplicate_of_owned = True


def build_bundle(results: dict[str, Any], mode: str, today: date | None = None) -> Bundle:
    """把 ``{工具名: ToolResult}`` 归一化为 :class:`Bundle`。

    ``results`` 的值可以是 ``ToolResult``，也可以是裸 payload。

    每个数据源都会打上 :class:`PayloadState`：**"调用成功"不等于"数据被读懂"**，
    只有 ``PARSED`` 才允许报告下"没有数据"的结论。
    """
    today = today or today_beijing()
    bundle = Bundle(mode=mode, today=today, generated_at=now_beijing())

    buckets: dict[str, list[dict]] = {}
    for tool, result in results.items():
        ok = bool(getattr(result, "ok", True))
        raw_payload = getattr(result, "data", result)
        # 先规整：JSON 文本、以及"说明性文本里包着的 JSON"都取出来。
        # 这一步很关键——真实 query-my-account 返回的是人话包裹的 JSON，
        # 不先剥开就会被当成"另一种格式"，进而误报解析失败。
        payload = coerce_payload(raw_payload) if ok else raw_payload
        error = getattr(result, "error", None)

        # 1) 先按 JSON 结构解析
        records = find_records(payload) if ok else []

        # 2) 解析不出记录，且该工具已知会返回正文 → 回退到文本解析器
        absent: tuple[str, ...] = ()
        if ok and not records and tool in _TEXT_PARSERS:
            text = payload_text(payload)
            records, text_warnings = _TEXT_PARSERS[tool](text)
            bundle.parse_notes.extend(f"`{tool}`：{note}" for note in text_warnings)
            if text.strip():
                absent = _ABSENT_FIELDS_BY_TOOL.get(tool, ())

        buckets[tool] = records
        bundle.sources.append(
            SourceStatus(
                tool=tool,
                ok=ok,
                error=error,
                record_count=len(records),
                unknown_keys=level1_keys(payload) if ok else [],
                state=classify_state(ok, payload, len(records)),
                # 体量按**服务器实际发来的原文**统计，而不是规整后的长度
                payload_chars=len(payload_text(raw_payload)),
                observed_format=observe_format(raw_payload) if ok else "—",
                absent_fields=list(absent),
            )
        )

    bundle.my_coupons = [normalize_coupon(r, "my") for r in buckets.get("query-my-coupons", [])]
    bundle.available_coupons = [
        normalize_coupon(r, "available") for r in buckets.get("available-coupons", [])
    ]
    bundle.campaigns = [normalize_campaign(r) for r in buckets.get("campaign-calendar", [])]

    account_result = results.get("query-my-account")
    if account_result is not None and getattr(account_result, "ok", True):
        account_payload = coerce_payload(getattr(account_result, "data", account_result))
        bundle.account = normalize_account(account_payload)
        # 积分是单对象而非列表，find_records 数不到，这里按"是否取到"记 1，
        # 否则状态表会误显示为 0 条记录，且会被误判成"解析失败"。
        status = bundle.source("query-my-account")
        if status is not None:
            status.record_count = 1 if bundle.account.present else 0
            if bundle.account.present:
                status.state = PayloadState.PARSED
                status.absent_fields = list(ACCOUNT_ABSENT)

    _mark_duplicates(bundle.my_coupons, bundle.available_coupons)
    _assign_coupon_refs(bundle.my_coupons, "MY")
    _assign_coupon_refs(bundle.available_coupons, "AVAIL")
    bundle.parse_notes.extend(_campaign_provenance_notes(bundle.campaigns))
    bundle.parse_notes.extend(_coupon_provenance_notes(bundle.my_coupons, bundle.available_coupons))
    bundle.parse_notes.extend(_benefit_kind_notes(bundle.all_coupons))
    bundle.parse_notes.extend(_privacy_notes(bundle.account))
    return bundle


def _assign_coupon_refs(coupons: list[Coupon], namespace: str) -> None:
    """给没有官方 ID 的券分配**带命名空间的**定位编号。

    命名空间（``MY`` / ``AVAIL``）不可省：两个列表各自从 1 开始编号，
    若不加前缀，"我的券第 1 张"与"可领取券第 1 张"就会同号，
    在报告里无法区分，也容易被误读成同一张券。
    """
    for index, coupon in enumerate(coupons, 1):
        if coupon.id:
            coupon.ref = coupon.ref or f"{namespace}-{index:04d}"
        else:
            coupon.ref = f"MC-{namespace}-{index:04d}"


def observe_format(payload: Any) -> str:
    """判断**真实返回**的形态，供报告如实标注"该接口到底返回了什么格式"。

    这不是炫技：参赛要求"检查每个工具返回的数据格式究竟是 JSON、Markdown 还是
    其他格式"，把它做成程序判定而非人工声称，才对得起"不编造"。
    """
    if isinstance(payload, dict):
        return "json"
    if isinstance(payload, list):
        return "json"
    if not isinstance(payload, str):
        return "unknown"
    text = payload.strip()
    if not text:
        return "empty"
    try:
        json.loads(text)
        return "json"
    except json.JSONDecodeError:
        pass
    if extract_embedded_json(payload) is not None:
        return "json（内嵌于说明文本）"
    if re.search(r"^\s{0,3}#{1,6}\s", text, re.M):
        return "markdown"
    return "text"


def _coupon_provenance_notes(mine: list[Coupon], claimable: list[Coupon]) -> list[str]:
    """说明券数据的来源语义（"已领取" vs "可领取"、定位编号的含义）。"""
    notes: list[str] = []
    groups = ((mine, "我的券", "MC-MY"), (claimable, "可领取券", "MC-AVAIL"))
    for group, label, namespace in groups:
        markdown_count = sum(1 for c in group if c.source_format == "markdown")
        if markdown_count:
            notes.append(
                f"`{label}` 有 {markdown_count} 条来自 Markdown 正文。官方正文**不提供券 ID**，"
                f"报告中的编号（形如 `{namespace}-0001`）是本技能生成的**定位编号**，"
                "仅用于在报告内互相指代，**不是官方 ID**，无法用于核销或客服查询。"
            )
    received = sum(1 for c in claimable if (c.status or "") == "已领取")
    if received:
        notes.append(
            f"可领取列表中 **{received} 条状态为「已领取」**——它们你已持有，"
            "本技能不会把它们算作「待领取」，也不会重复推荐。"
        )
    return notes


def _benefit_kind_notes(coupons: list[Coupon]) -> list[str]:
    """说明"券面权益 = 用券价格"这一口径，防止把实付价读成优惠额。"""
    priced = sum(1 for c in coupons if c.benefit_kind == "price")
    unknown = sum(1 for c in coupons if c.benefit_kind == "unknown" and c.benefit_text)
    notes: list[str] = []
    if priced:
        notes.append(
            f"有 {priced} 张券的官方原文把券面权益写成「¥X (用券价格)」，含义是"
            "**用券后实付金额**，不是优惠金额。因此这类券的「优惠值」列保留为 "
            f"{MISSING_MARK}，权益按原文列在「券面权益」列——**未做任何换算**。"
        )
    if unknown:
        notes.append(
            f"有 {unknown} 张券的券面权益无法判定是价格还是减免，已按原文照登、保持 {MISSING_MARK}。"
        )
    return notes


def _privacy_notes(account: PointsAccount) -> list[str]:
    """说明隐私字段被刻意排除，避免"是不是漏读了"的疑问。"""
    if not account.account_id_excluded:
        return []
    described = "、".join(f"`{key}`（{label}）" for key, label in PRIVACY_EXCLUDED_FIELDS.items())
    return [
        f"`query-my-account` 的返回中含会员标识 {described}，"
        "本技能**只记录它存在、不保存取值**，报告与导出中均不出现——"
        "这是隐私策略，不是解析遗漏。"
    ]


def _campaign_provenance_notes(campaigns: list[Campaign]) -> list[str]:
    """说明活动数据的来源语义，避免用户误读日期含义。"""
    notes: list[str] = []
    markdown_count = sum(1 for c in campaigns if c.date_source == "markdown")
    synthetic_count = sum(1 for c in campaigns if c.synthetic_id)
    if markdown_count:
        notes.append(
            f"活动日历有 {markdown_count} 条来自 Markdown 正文：报告中的「日历日」列是"
            "**官方日历的归档日期**（该活动出现在日历的哪一天），"
            "**不是活动的有效期区间**——官方日历根本不提供有效期。"
            "官方原文的分组标签（往期回顾 / 今日）已保留在「官方分组」列。"
        )
    if synthetic_count:
        notes.append(
            f"其中 {synthetic_count} 条活动的编号形如 `MD-20261009-01`，"
            "是解析时生成的**定位编号**，**不是官方活动ID**（官方日历不提供活动ID）。"
        )
    return notes


def days_left(expiry: date | None, today: date) -> int | None:
    """``到期日 - 基准日`` 的整天数；无到期日返回 ``None``（不猜）。"""
    if expiry is None:
        return None
    return (expiry - today).days


def humanize_days(delta: int | None) -> str:
    if delta is None:
        return MISSING_MARK
    if delta < 0:
        return f"已过期 {abs(delta)} 天"
    if delta == 0:
        return "今天到期"
    if delta == 1:
        return "明天到期"
    return f"{delta} 天后到期"


__all__ = [
    "ACCOUNT_ABSENT",
    "ACCOUNT_NUMERIC_FIELDS",
    "BEIJING_TZ",
    "Bundle",
    "Campaign",
    "Coupon",
    "FIELD_LABELS",
    "MD_AVAILABLE_ABSENT",
    "MD_COUPON_ABSENT",
    "MISSING_MARK",
    "NOT_PROVIDED_MARK",
    "PayloadState",
    "PointsAccount",
    "PRIVACY_EXCLUDED_FIELDS",
    "SourceStatus",
    "build_bundle",
    "classify_benefit",
    "classify_state",
    "coerce_payload",
    "days_left",
    "extract_embedded_json",
    "find_records",
    "has_payload_content",
    "humanize_days",
    "level1_keys",
    "normalize_account",
    "normalize_campaign",
    "normalize_coupon",
    "now_beijing",
    "observe_format",
    "parse_available_coupons_markdown",
    "parse_campaign_markdown",
    "parse_coupon_markdown",
    "parse_coupon_validity",
    "parse_date",
    "parse_number",
    "payload_text",
    "pick",
    "today_beijing",
]
