"""Interactive CLI for managing subscription redemption codes.

Usage:
    python scripts/manage_codes.py
"""

from __future__ import annotations

import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_PATH = PROJECT_DIR / "backend" / "data" / "subscriptions.db"

# Character set: uppercase + digits, excluding ambiguous chars (0, O, I, 1, L)
CHARSET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUP_SIZE = 5
NUM_GROUPS = 4


PLAN_CHOICES = {
    "1": ("plus", "Plus", "20次/天, 500次/月"),
    "2": ("pro", "Pro", "40次/天, 1000次/月"),
    "3": ("ultra", "Ultra", "100次/天, 3000次/月"),
}


def generate_code() -> str:
    """Generate a single redemption code: XXXXX-XXXXX-XXXXX-XXXXX."""
    groups = []
    for _ in range(NUM_GROUPS):
        group = "".join(secrets.choice(CHARSET) for _ in range(GROUP_SIZE))
        groups.append(group)
    return "-".join(groups)


def ensure_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            created_at TEXT NOT NULL,
            redeemed_by TEXT DEFAULT NULL,
            redeemed_at TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_fp TEXT NOT NULL,
            plan TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            code TEXT NOT NULL,
            FOREIGN KEY (code) REFERENCES codes(code)
        );

        CREATE INDEX IF NOT EXISTS idx_subs_fp ON subscriptions(device_fp);

        CREATE TABLE IF NOT EXISTS usage (
            device_fp TEXT NOT NULL,
            date TEXT NOT NULL,
            call_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (device_fp, date)
        );
    """)
    conn.commit()


def action_generate(conn: sqlite3.Connection) -> None:
    """Generate new redemption codes."""
    print("\n请选择套餐类型:")
    for key, (_, name, desc) in PLAN_CHOICES.items():
        print(f"  {key}. {name}  ({desc})")

    choice = input("\n> ").strip()
    if choice not in PLAN_CHOICES:
        print("无效选择")
        return

    plan_key, plan_name, _ = PLAN_CHOICES[choice]

    count_str = input("请输入生成数量: ").strip()
    try:
        count = int(count_str)
        if count < 1 or count > 1000:
            print("数量必须在 1-1000 之间")
            return
    except ValueError:
        print("请输入有效数字")
        return

    confirm = input(f"\n即将生成 {count} 个 {plan_name} 兑换码，确认? (y/n): ").strip().lower()
    if confirm != "y":
        print("已取消")
        return

    now = datetime.now(timezone.utc).isoformat()
    codes = []
    for _ in range(count):
        code = generate_code()
        codes.append((code, plan_key, now))

    conn.executemany(
        "INSERT INTO codes (code, plan, created_at) VALUES (?, ?, ?)",
        codes,
    )
    conn.commit()

    print(f"\n生成完成! 已存入数据库 ({DB_PATH}):\n")
    for code, _, _ in codes:
        print(code)


def action_list(conn: sqlite3.Connection) -> None:
    """List codes with optional filters."""
    print("\n查看哪类兑换码?")
    print("  1. 全部")
    print("  2. 未使用")
    print("  3. 已使用")

    choice = input("\n> ").strip()

    query = "SELECT code, plan, created_at, redeemed_by, redeemed_at FROM codes"
    params: list = []
    if choice == "2":
        query += " WHERE redeemed_by IS NULL"
    elif choice == "3":
        query += " WHERE redeemed_by IS NOT NULL"
    query += " ORDER BY created_at DESC LIMIT 100"

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        print("\n没有找到兑换码")
        return

    print(f"\n共 {len(rows)} 条记录:")
    print(f"{'兑换码':<25} {'套餐':<8} {'状态':<10} {'创建时间':<20}")
    print("-" * 65)
    for code, plan, created_at, redeemed_by, _ in rows:
        status = f"已用({redeemed_by[:8]}...)" if redeemed_by else "未使用"
        created = created_at[:19].replace("T", " ")
        print(f"{code:<25} {plan:<8} {status:<10} {created:<20}")


def action_stats(conn: sqlite3.Connection) -> None:
    """Show statistics."""
    print("\n===== 统计信息 =====\n")

    for key, (_, name, desc) in PLAN_CHOICES.items():
        cursor = conn.execute("SELECT COUNT(*) FROM codes WHERE plan = ?", (PLAN_CHOICES[key][0],))
        total = cursor.fetchone()[0]
        cursor = conn.execute(
            "SELECT COUNT(*) FROM codes WHERE plan = ? AND redeemed_by IS NOT NULL",
            (PLAN_CHOICES[key][0],),
        )
        used = cursor.fetchone()[0]
        print(f"{name} ({desc}): 总计 {total}, 已用 {used}, 剩余 {total - used}")

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "SELECT COUNT(DISTINCT device_fp) FROM subscriptions WHERE expires_at > ?",
        (now,),
    )
    active = cursor.fetchone()[0]
    print(f"\n活跃订阅设备数: {active}")


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_db(conn)

    try:
        while True:
            print("\n===== MCBE AI Commander 兑换码管理 =====")
            print("\n请选择操作:")
            print("  1. 生成兑换码")
            print("  2. 查看兑换码列表")
            print("  3. 查看统计信息")
            print("  4. 退出")

            choice = input("\n> ").strip()

            if choice == "1":
                action_generate(conn)
            elif choice == "2":
                action_list(conn)
            elif choice == "3":
                action_stats(conn)
            elif choice == "4":
                print("再见!")
                break
            else:
                print("无效选择，请重试")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
