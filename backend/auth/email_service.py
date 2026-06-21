"""Email verification service using Resend API."""

from __future__ import annotations

import asyncio
import logging

import resend

from backend.config import RESEND_API_KEY, RESEND_FROM_EMAIL

logger = logging.getLogger(__name__)


def _build_html(code: str, purpose: str) -> str:
    action = "注册账号" if purpose == "register" else "绑定邮箱"
    digits = list(code.ljust(6))

    digit_cells = "".join(
        f'<td style="width:44px;height:52px;background:#f8f9fa;border:1px solid #e9ecef;'
        f'border-radius:8px;text-align:center;font-size:28px;font-weight:700;'
        f'color:#1a1a2e;font-family:\'SF Mono\',\'Cascadia Code\',\'Consolas\',monospace;'
        f'letter-spacing:0">{d}</td>'
        for d in digits
    )

    return f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:40px 0">
<tr><td align="center">
<table width="420" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:32px 36px 28px;text-align:center">
    <div style="font-size:22px;font-weight:700;color:#ffaa00;letter-spacing:1px">BraynLabs</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:4px">账户安全验证</div>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:36px 36px 20px">
    <p style="margin:0 0 6px;font-size:16px;font-weight:600;color:#1a1a2e">您好，</p>
    <p style="margin:0 0 28px;font-size:14px;color:#555;line-height:1.6">
      您正在{action}，请使用以下验证码完成验证：
    </p>

    <!-- Code -->
    <table cellpadding="0" cellspacing="6" style="margin:0 auto 28px">
      <tr>{digit_cells}</tr>
    </table>

    <!-- Timer hint -->
    <div style="text-align:center;margin:0 0 28px">
      <span style="display:inline-block;background:#fff3e0;color:#e65100;font-size:12px;font-weight:500;padding:6px 16px;border-radius:20px">
        &#9200; 有效期 10 分钟
      </span>
    </div>

    <!-- Divider -->
    <hr style="border:none;border-top:1px solid #f0f0f0;margin:0 0 20px">

    <!-- Safety tips -->
    <p style="margin:0 0 4px;font-size:12px;color:#999;line-height:1.6">
      &#128274; 如果您没有进行此操作，请忽略这封邮件。请勿将验证码告知他人。
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#fafafa;padding:20px 36px;border-top:1px solid #f0f0f0;text-align:center">
    <p style="margin:0 0 4px;font-size:11px;color:#bbb">
      此邮件由 BraynLabs 系统自动发送，请勿直接回复
    </p>
    <p style="margin:0;font-size:11px;color:#bbb">
      <a href="https://commandcraft.cn" style="color:#999;text-decoration:none">CommandCraft</a>
      &nbsp;&middot;&nbsp;
      <a href="https://braynlabs.cn" style="color:#999;text-decoration:none">BraynLabs</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


async def send_verification_email(to_email: str, code: str, purpose: str) -> bool:
    """Send a verification code email via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set, skipping email send")
        return False

    resend.api_key = RESEND_API_KEY
    subject = f"{'注册' if purpose == 'register' else '绑定邮箱'}验证码 — BraynLabs"
    html = _build_html(code, purpose)

    try:
        result = await asyncio.to_thread(
            resend.Emails.send,
            {"from": RESEND_FROM_EMAIL, "to": [to_email], "subject": subject, "html": html},
        )
        ok = bool(result and getattr(result, "id", None))
        if ok:
            logger.info("Verification email sent to %s (purpose=%s)", to_email, purpose)
        return ok
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
        return False
