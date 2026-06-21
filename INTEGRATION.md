# WXpay 集成指南（给其它项目）

WXpay 跑在你本机一台 Mac 上，监听微信收款助手窗口、轮询识别收款消息、按订单号匹配。其它项目通过 HTTP 接入：**生成订单 → 引导用户付款备注里写订单号 → 服务自动检测 → 你拿状态**。

## TL;DR

```
1. POST /api/orders    →  拿到 order_id (6 位数字)
2. 提示用户付款，备注里写这个 order_id
3. 拿状态：
   ├─ 主动轮询：GET /api/orders/{id}
   └─ 或被动接收：创建订单时传 callback_url，状态变了服务会 POST 给你
```

## 端点 & 鉴权

- **Base URL**：`http://127.0.0.1:8000`（默认仅监听 loopback；调用方必须和 WXpay 在同一台机器）
- **写操作**（POST/DELETE）需要 `X-API-Key: <你的 key>`，key 在 WXpay 的 `.env` 里
- **查询订单**（`GET /api/orders/{id}`）**不需要 API Key**，方便高频轮询

### 速率限制（per-IP, token bucket）

为防一个跑飞的本地调用方把 SQLite / 微信窗口操作打满，所有路由都有内存级 token-bucket 限流。**超限返回 `429 Too Many Requests`，带 `Retry-After` 头（秒）。**

| 类别 | 适用路由 | 默认配额 | 配置项（`.env`） |
|---|---|---|---|
| `read` | `GET /api/orders/{id}`、`GET /healthz` | **600/min**（≈10 r/s, burst 600）| `WXPAY_RATE_LIMIT_READ_PER_MIN` |
| `write` | `POST /api/orders`、`DELETE /api/orders/{id}`、`GET /api/orders`(列表)、**所有 `/api/admin/*`** | **30/min**（≈0.5 r/s, burst 30）| `WXPAY_RATE_LIMIT_WRITE_PER_MIN` |

要点：
- **桶按 (类别, 客户端 IP) 分**——本机几乎所有调用方共享 `127.0.0.1` 这一个桶，按整机算总账。
- **capacity == 一分钟配额 == burst 上限**：可以一次把整分钟额度用完，然后等匀速回血（每秒 `quota/60`）。
- **建议轮询节奏**：`GET /api/orders/{id}` 每 2-5 秒一次足矣（10 r/s 的额度对单订单完全够），更紧的频率纯属浪费——后端轮询周期是 30 秒，更高频不会让你更早拿到结果。
- **遇到 429 怎么办**：读 `Retry-After` 头退避；不要无脑重试，会把桶继续打空。
- **写入 30/min 故意压低**：业务正常下单不会撞线（人不可能 1 秒内连下两单）；撞到说明你写错了循环。
- **加大限制**：调 `.env` 里两个 env 重启服务即可。生产建议用反向代理（nginx / cloudflare）做更细粒度的策略。

## 创建订单

```bash
curl -s -X POST http://127.0.0.1:8000/api/orders \
  -H "X-API-Key: $WXPAY_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_amount": "1.00",
    "ttl_seconds": 1800,
    "callback_url": "http://localhost:3000/wxpay-callback",
    "metadata": {"user_id": 42, "product": "100积分"}
  }'
```

请求体（全部字段都可选）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `expected_amount` | Decimal 字符串 | null | 期望金额（元）。**null = 不校验金额**（等于多少收多少都算 paid）|
| `ttl_seconds` | int | 1800 | 订单有效期，超过未付变 `expired` |
| `callback_url` | URL | null | 状态变化时 POST 通知（见 webhook 章节）|
| `metadata` | dict | null | 任意 JSON 元数据，原样回传 |

响应：

```json
{
  "order_id": "384192",
  "status": "pending",
  "expected_amount": "1.00",
  "expires_at": "2026-04-30T00:30:00",
  "payment_remark_hint": "请在付款备注中输入: 384192"
}
```

把 `order_id` 这 6 位数字告诉用户，让 ta **付款备注里包含**这串数字（前后可以带其它字，但必须有这 6 位连续数字）。`payment_remark_hint` 是格式化好的提示文案，直接展示给用户即可。

## 查订单状态

```bash
curl -s http://127.0.0.1:8000/api/orders/384192
```

响应：

```json
{
  "order_id": "384192",
  "status": "paid",
  "expected_amount": "1.00",
  "actual_amount": "1.00",
  "amount_diff": "0.00",
  "amount_diff_kind": "exact",
  "callback_url": null,
  "metadata": {"user_id": 42, "product": "100积分"},
  "raw_message": "个人收款服务\n收款到账通知\n...",
  "created_at": "2026-04-30T00:00:00",
  "expires_at": "2026-04-30T00:30:00",
  "paid_at": "2026-04-30T00:01:23"
}
```

### 订单状态

| `status` | 含义 | 调用方一般怎么处理 |
|---|---|---|
| `pending` | 等待付款 | 继续轮询 / 等 webhook |
| `paid` | 收到金额匹配的支付 | **发货** / 充值 / 完成业务流程 |
| `amount_mismatch` | 订单号匹配但金额不对 | 看 `amount_diff` 决定补差还是退款 |
| `expired` | 超时未付 | 引导用户重新下单 |
| `cancelled` | 调用方主动取消 | 不应该再处理 |

### `amount_diff` 字段（多付/少付）

仅在订单有 `expected_amount` 且已收到付款时有值，其它情况为 `null`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `amount_diff` | Decimal 字符串 / null | `actual - expected`。**正=多付**、**负=少付**、`0.00`=刚好 |
| `amount_diff_kind` | string / null | `exact` / `overpaid` / `underpaid` |

举例：

| 期望 | 实付 | `amount_diff` | `amount_diff_kind` | `status` |
|---|---|---|---|---|
| 1.00 | 1.00 | `0.00` | `exact` | `paid` |
| 1.00 | 2.50 | `1.50` | `overpaid` | `amount_mismatch` |
| 5.00 | 1.00 | `-4.00` | `underpaid` | `amount_mismatch` |
| null | 1.00 | `null` | `null` | `paid`（不校验） |

## 取消订单

```bash
curl -X DELETE http://127.0.0.1:8000/api/orders/384192 \
  -H "X-API-Key: $WXPAY_API_KEY"
```

`pending` 订单转为 `cancelled`；终态订单（paid / expired / 已 cancelled）返回 `409 Conflict`。

## Webhook（推送通知）

如果你创建订单时传了 `callback_url`，订单状态变成 `paid` 或 `amount_mismatch` 时 WXpay 会 POST 这个 URL：

```http
POST <你的 callback_url>
Content-Type: application/json
X-WXPay-Signature: <hex sha256 hmac of body>
X-WXPay-Order-Id: 384192

{
  "order_id": "384192",
  "status": "paid",
  "amount_cents": 100,
  "amount": "1.00",
  "expected_amount_cents": 100,
  "expected_amount": "1.00",
  "amount_diff_cents": 0,
  "amount_diff": "0.00",
  "amount_diff_kind": "exact",
  "payment_remark": "充值100积分384192",
  "occurred_at": "2026-04-29T23:29:00"
}
```

- 重试策略：失败重试 3 次，退避 5s / 30s / 120s。3 次都失败标 `dead`。
- 你的 endpoint 返回 `2xx` 视为成功；其它都算失败重试。
- **请校验签名**防止伪造（即便监听 loopback，也是好习惯）。

### 校验签名

WXpay 用 `WXPAY_WEBHOOK_SECRET`（在它的 `.env` 里）和请求体做 HMAC-SHA256，hex 编码后塞到 `X-WXPay-Signature` 头。你需要拿到同一个 secret 验证：

```python
# Python
import hmac, hashlib
def verify(secret: str, body: bytes, signature_hex: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex)
```

```javascript
// Node.js
const crypto = require("crypto");
function verify(secret, body, signatureHex) {
  const expected = crypto.createHmac("sha256", secret).update(body).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signatureHex));
}
```

```go
// Go
import "crypto/hmac"; "crypto/sha256"; "encoding/hex"
func Verify(secret string, body []byte, sigHex string) bool {
    mac := hmac.New(sha256.New, []byte(secret))
    mac.Write(body)
    expected := hex.EncodeToString(mac.Sum(nil))
    return hmac.Equal([]byte(expected), []byte(sigHex))
}
```

### 补发 Webhook（admin）

```bash
curl -X POST http://127.0.0.1:8000/api/admin/orders/384192/resend_webhook \
  -H "X-API-Key: $WXPAY_API_KEY"
```

把订单的 webhook 重新塞进发送队列，签名 / 重试策略和正常 webhook 完全一致。**何时用：**
- 原始 3 次重试都失败、job 被标记 `dead`（看 `webhook_jobs` 表）。
- 你的下游服务回滚 / 数据丢了。
- **轮询漏读了那笔消息**（例如本机出现过 `all_copy_tiers_failed` 把订单卡住），事后你手动改了 DB 把订单转成 `paid`，但回调没自动触发。

约束：
- 订单必须存在（否则 404）。
- 订单状态必须是 `paid` 或 `amount_mismatch`（其它状态 409）。
- 订单必须有 `callback_url`（否则 422）。
- 走 `write` 类速率限制。
- 不会去重——同一订单连续调用会发同样多条 webhook，下游自己幂等。

响应：

```json
{ "ok": true, "job_id": 17, "order_id": "384192", "url": "http://...", "status": "paid" }
```

## 健康检查

```bash
curl -s http://127.0.0.1:8000/healthz
```

调用前可以先打这个判断 WXpay 是否就绪：

```json
{
  "ok": true,
  "polling_enabled": true,        // 用户开关是否打开（桌面 WXPAY_ON.txt 是否存在）
  "ax_trusted": true,             // 辅助功能权限
  "wechat_running": true,
  "wechat_version": "4.1.9",
  "last_poll_at": "2026-04-30T00:30:00",
  "last_poll_ok": true,
  "last_error": null,
  "pending_orders_count": 2,
  ...
}
```

**重要**：`polling_enabled = false` 时 WXpay 不会检测付款（用户主动暂停了）。你应该提示用户去打开开关（桌面 `WXPAY_ON.txt` 文件 / `Cmd+Shift+P` 快捷键 / 调 `POST /api/admin/switch/on`）再下单。

## 完整集成示例

### Python（同步轮询）

```python
import time, requests
BASE = "http://127.0.0.1:8000"
HEADERS = {"X-API-Key": "wxp_live_xxx"}

def collect_payment(amount: str, ttl: int = 600) -> dict:
    # 1. 建单
    r = requests.post(f"{BASE}/api/orders", headers=HEADERS,
                      json={"expected_amount": amount, "ttl_seconds": ttl})
    r.raise_for_status()
    order = r.json()

    # 2. 提示用户
    print(f"请扫码付款 ¥{amount}，备注里输入: {order['order_id']}")

    # 3. 轮询
    deadline = time.time() + ttl
    while time.time() < deadline:
        time.sleep(3)
        s = requests.get(f"{BASE}/api/orders/{order['order_id']}").json()
        if s["status"] in ("paid", "amount_mismatch", "expired", "cancelled"):
            return s
    return {"status": "expired"}

# 用法
result = collect_payment("1.00")
if result["status"] == "paid":
    print("付款成功！")
elif result["status"] == "amount_mismatch":
    print(f"金额不对：{result['amount_diff_kind']}, 差额 {result['amount_diff']}")
```

### Node.js（webhook 接收）

```javascript
const express = require("express");
const crypto = require("crypto");
const app = express();
const SECRET = process.env.WXPAY_WEBHOOK_SECRET;

app.post("/wxpay-callback", express.raw({ type: "application/json" }), (req, res) => {
  const sig = req.get("X-WXPay-Signature");
  const expected = crypto.createHmac("sha256", SECRET).update(req.body).digest("hex");
  if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig || ""))) {
    return res.status(401).send("bad signature");
  }
  const event = JSON.parse(req.body);
  if (event.status === "paid") {
    fulfillOrder(event.order_id, event.metadata, event.amount);
  } else if (event.status === "amount_mismatch") {
    handleMismatch(event.order_id, event.amount_diff, event.amount_diff_kind);
  }
  res.status(200).end();
});

// 创建订单
async function createOrder(amount, productId) {
  const r = await fetch("http://127.0.0.1:8000/api/orders", {
    method: "POST",
    headers: { "X-API-Key": process.env.WXPAY_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      expected_amount: amount,
      ttl_seconds: 1800,
      callback_url: "http://localhost:3000/wxpay-callback",
      metadata: { product_id: productId },
    }),
  });
  return r.json();
}
```

## 常见错误

| HTTP | 触发条件 | 怎么处理 |
|---|---|---|
| `401 invalid API key` | `X-API-Key` 缺失或不对 | 检查 `.env` |
| `404 order not found` | order_id 不存在 | 用户输错了 / 订单被清掉了 |
| `409 order is in terminal status: ...` | 取消已经终态的订单 | 直接读最新状态即可 |
| `429 rate limit exceeded` | 触发上面的速率限制 | 看 `Retry-After` 退避，别立刻重试 |
| `503 failed to generate unique order_id` | 撞车 8 次（极罕见，需要同时上百万 pending）| 重试 |
| 连不上 | WXpay 服务没启动 / 端口被占 | 跑 `make run`，看 `:8000` 是否在监听 |

## 行为提醒（必看）

- **6 位订单号有 1/100w 撞车概率**：同时大量未支付订单时（>1万）建议加业务侧二次校验（比如检查 `metadata.user_id`）。
- **付款人备注里有多个 6 位连续数字**（例如 "20260430 充值 384192"）：WXpay 把所有 6 位 candidates 都查一遍，命中多个时按 `created_at DESC` 取最新，**不会**乱匹配。但仍建议引导用户**只**输订单号。
- **`amount_mismatch` 订单不会自动补差或返还差额**：这是业务逻辑层的事，调用方自己定（拒收 / 给奖励 / 退差等）。
- **每次轮询会"打断"用户**：WXpay 按窗口画面变化按需轮询，多数时间不抢焦点；但每次真正要读消息时会把 WeChat 拉到前台 ~1 秒。
- **重启 Mac 后默认暂停**：用户必须手动打开 WeChat + 收款助手窗口 + 打开桌面开关（`WXPAY_ON.txt`），WXpay 才会开始轮询。健康检查里 `polling_enabled` 是真相之源。

## 测试

```bash
# Dry-run：把任意收款消息文本喂给 parser+matcher，看会怎么解析（不落库）
curl -X POST http://127.0.0.1:8000/api/admin/dry_run_match \
  -H "X-API-Key: $WXPAY_API_KEY" \
  -d '{"raw_text": "收款到账通知\n收款金额\n¥1.00\n付款方备注: 384192\n汇总: 今日第1笔\n备注: ok"}'
```
