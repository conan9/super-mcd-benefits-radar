"""麦当劳中国 MCP Server 只读客户端。

设计要点
--------
1. **白名单 + 默认拒绝**：只有 ``READ_ONLY_TOOLS`` 中的工具可被调用，
   其余一律抛 :class:`WriteOperationBlocked`。这是本技能"不下单、不消费积分、
   不自动领券"承诺的技术落点，而非文档约定。
2. **双模式严格分离**：``mock`` 只读本地 fixtures，绝不联网；
   ``real`` 才连接 ``https://mcp.mcd.cn``。
3. **Token 永不落盘、永不回显**：仅从环境变量 ``MCD_MCP_TOKEN`` 读取，
   所有对外字符串统一经过 :func:`redact`。
4. **纯标准库**：使用 ``urllib.request`` 与 ``json``，无第三方依赖。

官方文档：[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://mcp.mcd.cn"
DEFAULT_TIMEOUT = 20
PROTOCOL_VERSION = "2025-06-18"

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"

#: 本技能实际使用的四个查询工具（官方 README v1.0.9 工具列表）
OFFICIAL_TOOLS: dict[str, str] = {
    "query-my-coupons": "我的优惠券查询：查询用户有哪些可用的优惠券",
    "query-my-account": "我的积分查询：可用积分、累计积分、冻结积分、即将过期积分",
    "available-coupons": "麦麦省券列表查询：查询当前可领取的券",
    "campaign-calendar": "活动日历查询工具：当月营销活动日历",
}

#: 允许调用的只读工具集合（真正的执行白名单）
READ_ONLY_TOOLS: frozenset[str] = frozenset(OFFICIAL_TOOLS) | {"now-time-info"}

#: 明确禁止的写入/交易类工具（用于生成更友好的错误提示）
DENIED_TOOLS: dict[str, str] = {
    "auto-bind-coupons": "自动领券",
    "point-redemption": "积分兑换券",
    "mall-create-order": "积分兑换下单",
    "mcdelivery-order": "麦乐送下单",
    "pickup-order": "到店取餐下单",
    "group-meal-order": "团餐下单",
    "party-order-create": "主题活动下单",
    "draw-lottery": "积分抽奖（消耗积分）",
}

_HEADER = "Authorization"

#: 脱敏规则表：(正则, 替换串)
#: 设计取向——**宁可过度脱敏，也不放过一枚 Token**。
#: 因此长十六进制/base64url 串不做词边界限制（``\b`` 在 ``sk_live_xxx`` 场景下会失效，
#: 这曾导致一枚 40 位密钥漏过脱敏）。代价是极少数长串 ID 会被显示为 ``***``，
#: 这对"不编造"原则无害：脱敏是遮蔽，不是填充。
_REDACT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer)\s+\S+"), r"\1 ***"),
    (
        re.compile(
            r'(?i)("(?:authorization|token|access[_-]?token|api[_-]?key|mcp[_-]?token|secret)"\s*:\s*)"[^"]*"'
        ),
        r"\1 ***",
    ),
    (re.compile(r"(?i)((?:sk|pk|key|token|secret)[_-])[A-Za-z0-9_\-]{12,}"), r"\1***"),
    (re.compile(r"[0-9a-fA-F]{32,}"), "***"),
    (re.compile(r"[A-Za-z0-9_\-]{40,}"), "***"),
)


class MCPError(RuntimeError):
    """MCP 相关错误基类。"""


class MCPAuthError(MCPError):
    """Token 无效、过期或未提供（HTTP 401 / 403）。"""


class MCPRateLimitError(MCPError):
    """触发限流（HTTP 429，官方限制 600 次/分钟）。"""


class MCPTransportError(MCPError):
    """网络或协议层错误。"""


class WriteOperationBlocked(MCPError):
    """试图调用非只读工具——被白名单拦截。"""


def redact(text: Any, secrets: list[str] | None = None) -> str:
    """对任意对象做字符串化脱敏，保证 Token 不会出现在输出中。

    处理顺序：先按已知密钥精确替换，再套用通用规则表兜底。
    通用规则中的长串匹配**不带词边界**，是为了不放过 ``sk_live_<hex>`` 这类形态。
    """
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    for secret in secrets or []:
        if secret and len(secret) >= 6:
            s = s.replace(secret, "***")
    for pattern, replacement in _REDACT_RULES:
        s = pattern.sub(replacement, s)
    return s


#: 会员身份类字段——**结构保留、值就地掩码**。
#: 与 :func:`redact` 的区别：redact 是"宁可过度遮蔽"，会把 32 位十六进制
#: 一律打成 ``***``，那样 ``--dump-raw`` 就失去了核对 schema 的意义。
#: 这里只遮蔽**明确属于个人/凭据**的键，键名与其它值原样保留，
#: 既守住隐私，又让字段映射能用真实结构收敛。
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "accountid",
        "account_id",
        "userid",
        "user_id",
        "memberid",
        "member_id",
        "openid",
        "open_id",
        "unionid",
        "union_id",
        "phone",
        "mobile",
        "mobilephone",
        "mobile_phone",
        "telephone",
        "token",
        "accesstoken",
        "access_token",
        "traceid",
        "trace_id",
    }
)

MASK = "<已按隐私策略掩码>"

#: 带签名的临时 URL：签名段是**有时效的凭据**，只保留路径便于核对结构
_SIGNED_QUERY_RE = re.compile(r"([?&])(sign|q-signature|q-ak|q-sign-time|q-key-time)=[^&\s]*", re.I)


def mask_sensitive(node: Any, _depth: int = 0) -> Any:
    """递归掩码个人标识与签名参数，**保持结构不变**（供 ``--dump-raw`` 使用）。"""
    if _depth > 12:
        return node
    if isinstance(node, dict):
        masked: dict = {}
        for key, value in node.items():
            if str(key).strip().lower() in SENSITIVE_KEYS:
                masked[key] = MASK
            else:
                masked[key] = mask_sensitive(value, _depth + 1)
        return masked
    if isinstance(node, list):
        return [mask_sensitive(item, _depth + 1) for item in node]
    if isinstance(node, str):
        return _SIGNED_QUERY_RE.sub(r"\1\2=<已掩码>", node)
    return node


_PLACEHOLDER_RE = re.compile(r"\$\{TODAY(?:([+-])(\d+))?\}")


def resolve_placeholders(text: str, today: date | None = None) -> str:
    """把样例数据里的 ``${TODAY}`` / ``${TODAY+3}`` / ``${TODAY-30}`` 解析为真实日期。

    这样 fixtures 不会随日历漂移，"今天到期""3 天后到期"这类断言永远成立。
    """
    base = today or date.today()

    def _sub(match: re.Match[str]) -> str:
        sign, days = match.group(1), match.group(2)
        if not days:
            offset = 0
        else:
            offset = int(days) if sign == "+" else -int(days)
        return (base + timedelta(days=offset)).isoformat()

    return _PLACEHOLDER_RE.sub(_sub, text)


@dataclass
class ToolResult:
    """统一封装一次工具调用的结果，便于上层判断"成功 / 失败 / 缺字段 / 被拦截"。"""

    tool: str
    ok: bool
    data: Any = None
    error: str | None = None
    mode: str = "mock"
    blocked: bool = False

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "mode": self.mode,
            "blocked": self.blocked,
        }


# --------------------------------------------------------------------------- #
# 传输层
# --------------------------------------------------------------------------- #
class MockTransport:
    """离线传输层：按工具名读取 ``fixtures/`` 下的样例数据。

    两种样例格式，用环境变量 ``MCD_MOCK_FORMAT`` 切换：

    * 默认 ``json`` —— 结构化的**合成**样例，用于演示与 JSON 解析路径回归。
    * ``real`` —— **官方响应格式的合成样例**（结构逐行对标真实响应，取值全部合成），
      用于回放线上格式（Markdown / 说明文本包裹的 JSON）。
      这使"离线跑一遍"与"线上跑一遍"走的是同一套输入格式。

    支持通过环境变量 ``MCD_MOCK_FAIL`` 注入失败（逗号分隔的工具名），
    用于验证"单个数据源失败不影响整份报告"的降级逻辑。
    """

    mode = "mock"

    #: 样例后缀的搜索顺序（``real`` 优先，找不到再退回 JSON）
    _REAL_SUFFIXES: tuple[str, ...] = (".md", ".txt")
    _JSON_SUFFIXES: tuple[str, ...] = (".json",)

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self.fixture_dir = fixture_dir or FIXTURE_DIR
        self.failing = {t.strip() for t in os.environ.get("MCD_MOCK_FAIL", "").split(",") if t.strip()}
        self.format = os.environ.get("MCD_MOCK_FORMAT", "json").strip().lower() or "json"

    def _suffix_order(self) -> tuple[str, ...]:
        if self.format in {"real", "md", "markdown", "text", "txt"}:
            return (*self._REAL_SUFFIXES, *self._JSON_SUFFIXES)
        return self._JSON_SUFFIXES

    def fixture_path(self, name: str) -> Path | None:
        stem = name.replace("-", "_")
        for suffix in self._suffix_order():
            candidate = self.fixture_dir / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
        return None

    def rpc(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": "mcd-mcp (mock)", "version": "mock"},
                "capabilities": {"tools": {}},
            }
        if method == "tools/list":
            return {"tools": [{"name": n, "description": d} for n, d in OFFICIAL_TOOLS.items()]}
        if method == "tools/call":
            name = params.get("name", "")
            if name in self.failing:
                raise MCPToolError(f"[mock] 工具 {name} 被要求模拟失败")
            path = self.fixture_path(name)
            if path is None:
                raise MCPToolError(f"[mock] 缺少样例数据: {name.replace('-', '_')}.json|.md|.txt")
            return {"content": [{"type": "text", "text": resolve_placeholders(path.read_text(encoding="utf-8"))}]}
        raise MCPTransportError(f"[mock] 不支持的方法: {method}")


class MCPToolError(MCPError):
    """工具执行层面的错误。"""


class StreamableHTTPTransport:
    """官方远程端点传输层（Streamable HTTP）。

    - ``POST`` JSON-RPC 到 ``MCD_MCP_URL``（默认 ``https://mcp.mcd.cn``）
    - ``Accept: application/json, text/event-stream``
    - 响应可能是 SSE（``data: {...}`` 行）或纯 JSON，两种都能解析
    """

    mode = "real"

    def __init__(self, token: str | None = None, url: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.token = token if token is not None else os.environ.get("MCD_MCP_TOKEN", "")
        self.url = url or os.environ.get("MCD_MCP_URL", DEFAULT_URL)
        self.timeout = timeout
        self._id = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "super-mcd-benefits-radar/1.0",
        }
        if self.token:
            headers[_HEADER] = f"Bearer {self.token}"
        return headers

    def rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            code = exc.code
            detail = redact(exc.read().decode("utf-8", errors="replace")[:400], [self.token])
            if code in (401, 403):
                raise MCPAuthError(f"HTTP {code}：MCP Token 无效、已过期或未提供。{detail}") from None
            if code == 429:
                raise MCPRateLimitError("HTTP 429：触发限流（官方限制 600 次/分钟），请降低频率。") from None
            raise MCPTransportError(f"HTTP {code}：{detail}") from None
        except urllib.error.URLError as exc:
            raise MCPTransportError(f"网络不可达：{redact(str(exc.reason), [self.token])}") from None

        return self._parse(body)

    def _parse(self, body: str) -> dict:
        """兼容 SSE 与纯 JSON 两种响应形态。"""
        body = body.strip()
        if not body:
            raise MCPTransportError("响应体为空")
        if body.startswith("{"):
            return self._unwrap(json.loads(body))
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    return self._unwrap(json.loads(chunk))
                except json.JSONDecodeError:
                    continue
        raise MCPTransportError("无法解析响应：既非 JSON 也无可用的 SSE data 帧")

    @staticmethod
    def _unwrap(obj: dict) -> dict:
        if "error" in obj and obj["error"]:
            err = obj["error"]
            raise MCPTransportError(f"JSON-RPC 错误 {err.get('code')}: {err.get('message')}")
        return obj.get("result", obj)


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
@dataclass
class MCDClient:
    """只读 MCP 客户端。参见模块顶部说明。"""

    mode: str = "mock"
    transport: Any = None
    secrets: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    _initialized: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("mock", "real"):
            raise ValueError(f"未知模式: {self.mode!r}，仅支持 'mock' 或 'real'")
        if self.transport is None:
            if self.mode == "mock":
                self.transport = MockTransport()
            else:
                token = os.environ.get("MCD_MCP_TOKEN", "")
                if not token:
                    raise MCPAuthError(
                        "real 模式需要环境变量 MCD_MCP_TOKEN。\n"
                        "  1) 前往 https://open.mcd.cn/mcp 申请 Token\n"
                        "  2) export MCD_MCP_TOKEN=你的Token（勿写入文件、勿提交仓库）\n"
                        "  3) 或改用 --mode mock 离线体验"
                    )
                self.transport = StreamableHTTPTransport(token=token)
                self.secrets.append(token)

    # -- 协议 -------------------------------------------------------------- #
    def initialize(self) -> dict:
        result = self.transport.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "super-mcd-benefits-radar", "version": "1.0.0"},
            },
        )
        self._initialized = True
        return result

    def list_tools(self) -> list[str]:
        result = self.transport.rpc("tools/list", {})
        return [t.get("name", "") for t in result.get("tools", [])]

    # -- 白名单门禁 -------------------------------------------------------- #
    @staticmethod
    def assert_read_only(tool: str) -> None:
        """只读门禁：非白名单工具一律拒绝。"""
        if tool in READ_ONLY_TOOLS:
            return
        reason = DENIED_TOOLS.get(tool)
        if reason:
            raise WriteOperationBlocked(
                f"已拒绝调用 {tool!r}（{reason}）。"
                "超麦权益雷达是纯只读技能：不下单、不消费积分、不自动领券。"
                "请由用户本人在麦当劳 App 内完成该操作。"
            )
        raise WriteOperationBlocked(
            f"已拒绝调用 {tool!r}：该工具不在只读白名单内（默认拒绝策略）。"
            f"允许的工具：{', '.join(sorted(READ_ONLY_TOOLS))}"
        )

    # -- 只读查询 ---------------------------------------------------------- #
    def call_tool(self, tool: str, arguments: dict | None = None) -> ToolResult:
        """调用一个只读工具，任何异常都被收敛为 ``ToolResult(ok=False)``。"""
        try:
            self.assert_read_only(tool)
        except WriteOperationBlocked as exc:
            return ToolResult(tool=tool, ok=False, error=str(exc), mode=self.mode, blocked=True)

        self.calls.append(tool)
        try:
            result = self.transport.rpc("tools/call", {"name": tool, "arguments": arguments or {}})
            return ToolResult(tool=tool, ok=True, data=self._extract_text(result), mode=self.mode)
        except MCPError as exc:
            return ToolResult(tool=tool, ok=False, error=redact(str(exc), self.secrets), mode=self.mode)

    def _extract_text(self, result: dict) -> Any:
        """从 MCP content 数组中取出文本并尝试解析为 JSON。"""
        if not isinstance(result, dict):
            return result
        blocks = result.get("content")
        if not isinstance(blocks, list):
            return result.get("structuredContent", result)
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        if len(texts) == 1:
            return _maybe_json(texts[0])
        return [_maybe_json(t) for t in texts]

    def close(self) -> None:  # 预留，urllib 无持久连接
        self._initialized = False


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def mode_from_env(argv_mode: str | None = None) -> str:
    """决定运行模式：显式参数 > 环境变量 > 无 Token 时兜底 mock。"""
    if argv_mode:
        return argv_mode
    env_mode = os.environ.get("MCD_MODE", "").strip().lower()
    if env_mode in ("mock", "real"):
        return env_mode
    return "real" if os.environ.get("MCD_MCP_TOKEN") else "mock"


def build_client(mode: str | None = None) -> MCDClient:
    """工厂：按模式构建客户端。"""
    return MCDClient(mode=mode_from_env(mode))


__all__ = [
    "DEFAULT_URL",
    "OFFICIAL_TOOLS",
    "READ_ONLY_TOOLS",
    "DENIED_TOOLS",
    "MASK",
    "SENSITIVE_KEYS",
    "MCDClient",
    "MockTransport",
    "ToolResult",
    "MCPError",
    "MCPAuthError",
    "MCPRateLimitError",
    "MCPTransportError",
    "MCPToolError",
    "WriteOperationBlocked",
    "build_client",
    "mask_sensitive",
    "mode_from_env",
    "redact",
    "resolve_placeholders",
]
