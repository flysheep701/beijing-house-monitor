#!/usr/bin/env python3
"""
微信通知推送（可选）
通过 webhook 将每日摘要推送到微信
需要在 GitHub Secrets 中设置 WECHAT_WEBHOOK_URL
"""

import json
import os
import glob
from datetime import datetime
from pathlib import Path

import requests


def get_latest_data():
    """获取最新数据"""
    data_dir = Path("data_history")
    files = sorted(glob.glob(str(data_dir / "*.json")), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def build_message(data):
    """构建推送消息"""
    date_str = data.get("date", "")
    total = data.get("total_qualified", 0)
    changes = data.get("changes", {})

    msg = f"📊 北京购房监控日报 - {date_str}\n\n"
    msg += f"📈 今日概况：符合条件 {total} 套\n\n"

    # 变化摘要
    new_count = changes.get("new_count", 0)
    removed_count = changes.get("removed_count", 0)
    price_change_count = changes.get("price_change_count", 0)

    if new_count == 0 and removed_count == 0 and price_change_count == 0:
        msg += "🔔 变化摘要：\n✅ 今日无重大变化，房源数据与昨日基本一致。\n\n"
    else:
        msg += "🔔 变化摘要：\n"
        if new_count > 0:
            msg += f"🆕 新上线 {new_count} 套：\n"
            for nl in changes.get("new_listings", []):
                msg += f"  - {nl.get('community','')} | {nl.get('layout','')} | {nl.get('area','')}㎡ | {int(nl.get('total_price',0))}万\n"
        if removed_count > 0:
            msg += f"❌ 已下线 {removed_count} 套\n"
        if price_change_count > 0:
            msg += f"💰 价格变动 {price_change_count} 套：\n"
            for pc in changes.get("price_changes", []):
                diff = pc.get("new_price", 0) - pc.get("old_price", 0)
                arrow = "↑" if diff > 0 else "↓"
                msg += f"  - {pc.get('community','')} {pc.get('area','')}㎡: {int(pc.get('old_price',0))}万→{int(pc.get('new_price',0))}万({arrow}{abs(int(diff))}万)\n"
        msg += "\n"

    # 各小区概况
    msg += "📋 各小区在售情况：\n"
    for name, community_data in data.get("communities", {}).items():
        count = community_data.get("count", 0)
        listings = community_data.get("listings", [])
        if listings:
            prices = [l.get("total_price", 0) for l in listings if l.get("total_price")]
            areas = [l.get("area", 0) for l in listings if l.get("area")]
            price_range = f"{int(min(prices))}-{int(max(prices))}万" if prices else "N/A"
            area_range = f"{int(min(areas))}-{int(max(areas))}㎡" if areas else "N/A"
            msg += f"  - {name}：{count}套（{price_range}，{area_range}）\n"
        else:
            msg += f"  - {name}：{count}套\n"

    msg += "\n详细报告已更新，请查看网页。"
    return msg


def send_wechat(message):
    """发送微信通知"""
    webhook_url = os.environ.get("WECHAT_WEBHOOK_URL", "")
    if not webhook_url:
        print("⚠️ 未设置 WECHAT_WEBHOOK_URL，跳过推送")
        return

    payload = {
        "msgtype": "text",
        "text": {"content": message}
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            print("✅ 微信通知已推送")
        else:
            print(f"⚠️ 推送失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")


def main():
    data = get_latest_data()
    if not data:
        print("❌ 没有数据可推送")
        return

    message = build_message(data)
    print("📨 推送内容：")
    print(message)
    print()

    send_wechat(message)


if __name__ == "__main__":
    main()
