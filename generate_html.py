#!/usr/bin/env python3
"""
北京二手房监控 - HTML报告生成器
读取采集到的JSON数据，生成美观的HTML监控报告
"""

import json
import os
import glob
from datetime import datetime
from pathlib import Path


def get_latest_data_file():
    """获取最新的数据文件"""
    data_dir = Path("data_history")
    if not data_dir.exists():
        return None

    files = sorted(glob.glob(str(data_dir / "*.json")), reverse=True)
    if not files:
        return None

    return files[0]


def get_previous_data_file(current_file):
    """获取前一天的数据文件"""
    data_dir = Path("data_history")
    files = sorted(glob.glob(str(data_dir / "*.json")), reverse=True)

    current_name = os.path.basename(current_file)
    for i, f in enumerate(files):
        if os.path.basename(f) == current_name and i + 1 < len(files):
            return files[i + 1]
    return None


def format_number(num):
    """格式化数字，加千分位"""
    if isinstance(num, int):
        return f"{num:,}"
    return str(num)


def generate_html(data):
    """生成完整的HTML报告"""

    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y年%m月%d日")
    source = data.get("source", "链家")
    total = data.get("total_qualified", 0)
    collection_note = data.get("collection_note", "")

    changes = data.get("changes", {})
    new_count = changes.get("new_count", 0)
    removed_count = changes.get("removed_count", 0)
    price_change_count = changes.get("price_change_count", 0)

    # 计算价格和面积区间
    all_prices = []
    all_areas = []
    for community_data in data.get("communities", {}).values():
        for listing in community_data.get("listings", []):
            if listing.get("total_price"):
                all_prices.append(listing["total_price"])
            if listing.get("area"):
                all_areas.append(listing["area"])

    price_range = f"{int(min(all_prices))}-{int(max(all_prices))}" if all_prices else "N/A"
    area_range = f"{int(min(all_areas))}-{int(max(all_areas))}" if all_areas else "N/A"

    # 构建HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>北京二手房监控 - 链家数据整理</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
            background: #f0f2f5;
            color: #333;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            text-align: center;
            color: #1a1a2e;
            font-size: 28px;
            margin-bottom: 8px;
            font-weight: 700;
        }}
        .subtitle {{
            text-align: center;
            color: #888;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            text-align: center;
        }}
        .summary-card .number {{
            font-size: 36px;
            font-weight: 700;
            color: #e74c3c;
        }}
        .summary-card .label {{
            font-size: 14px;
            color: #888;
            margin-top: 4px;
        }}
        .summary-card.green .number {{ color: #27ae60; }}
        .summary-card.blue .number {{ color: #2980b9; }}
        .summary-card.orange .number {{ color: #e67e22; }}
        .summary-card.purple .number {{ color: #8e44ad; }}

        .section {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }}
        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .section-title {{
            font-size: 20px;
            font-weight: 700;
            color: #1a1a2e;
        }}
        .section-badge {{
            display: inline-block;
            background: #e74c3c;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        .section-badge.green {{ background: #27ae60; }}
        .section-badge.blue {{ background: #2980b9; }}
        .section-badge.orange {{ background: #e67e22; }}
        .section-badge.purple {{ background: #8e44ad; }}

        .filter-info {{
            font-size: 13px;
            color: #999;
            margin-bottom: 12px;
            padding: 8px 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 3px solid #2980b9;
        }}

        .table-wrapper {{
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            min-width: 1100px;
        }}
        thead th {{
            background: #1a1a2e;
            color: white;
            padding: 12px 10px;
            text-align: center;
            font-weight: 600;
            white-space: nowrap;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        tbody td {{
            padding: 10px;
            text-align: center;
            border-bottom: 1px solid #eee;
            white-space: nowrap;
        }}
        tbody tr:hover {{
            background: #f0f7ff;
        }}
        tbody tr:nth-child(even) {{
            background: #fafbfc;
        }}
        tbody tr:nth-child(even):hover {{
            background: #f0f7ff;
        }}
        .price-total {{
            font-weight: 700;
            color: #e74c3c;
            font-size: 16px;
        }}
        .price-unit {{
            color: #666;
            font-size: 12px;
        }}
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }}
        .tag-2room {{ background: #e8f5e9; color: #2e7d32; }}
        .tag-3room {{ background: #e3f2fd; color: #1565c0; }}
        .tag-1room {{ background: #fff3e0; color: #e65100; }}

        .highlight-row {{
            background: #fffde7 !important;
        }}
        .highlight-row:hover {{
            background: #fff9c4 !important;
        }}

        .change-new {{ background: #e8f5e9 !important; }}
        .change-price-down {{ background: #e8f5e9 !important; }}
        .change-price-up {{ background: #fff3e0 !important; }}

        .no-data {{
            text-align: center;
            padding: 40px;
            color: #aaa;
            font-size: 16px;
        }}
        .no-data .icon {{
            font-size: 48px;
            margin-bottom: 12px;
        }}

        .notes {{
            background: #fff8e1;
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
            border-left: 4px solid #ffc107;
        }}
        .notes h3 {{
            color: #f57f17;
            margin-bottom: 10px;
            font-size: 16px;
        }}
        .notes ul {{
            padding-left: 20px;
            color: #666;
        }}
        .notes li {{
            margin-bottom: 6px;
            font-size: 13px;
        }}

        .data-source {{
            text-align: center;
            color: #bbb;
            font-size: 12px;
            margin-top: 20px;
            padding: 10px;
        }}

        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            h1 {{ font-size: 22px; }}
            .section {{ padding: 16px; }}
            table {{ font-size: 12px; }}
            thead th {{ padding: 8px 6px; }}
            tbody td {{ padding: 8px 6px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 北京二手房监控报告</h1>
        <p class="subtitle">数据采集时间：{date_display} | 数据来源：{source}</p>

        <div class="summary-cards">
            <div class="summary-card">
                <div class="number">{len(data.get('communities', {}))}</div>
                <div class="label">监控小区</div>
            </div>
            <div class="summary-card green">
                <div class="number">{total}</div>
                <div class="label">符合条件房源</div>
            </div>
            <div class="summary-card blue">
                <div class="number">{price_range}</div>
                <div class="label">总价区间（万）</div>
            </div>
            <div class="summary-card orange">
                <div class="number">{area_range}</div>
                <div class="label">面积区间（㎡）</div>
            </div>
        </div>
"""

    # 采集状态说明（如果有）
    if collection_note:
        html += f"""
        <div class="section" style="background: #fff3e0; border-left: 4px solid #ff9800;">
            <div class="section-header">
                <span class="section-title">⚠️ 今日采集说明</span>
            </div>
            <p style="font-size: 14px; color: #666; line-height: 1.8;">
                {collection_note}
            </p>
        </div>
"""

    # 今日变化
    html += _generate_changes_section(changes, date_display, data)

    # 各小区详情
    badge_colors = ["", "green", "blue", "orange", "purple"]
    community_icons = ["①", "②", "③", "④", "⑤"]
    new_listing_ids = set()
    for nl in changes.get("new_listings", []):
        key = f"{nl.get('community','')}-{nl.get('area',0)}-{nl.get('total_price',0)}"
        new_listing_ids.add(key)

    price_change_map = {}
    for pc in changes.get("price_changes", []):
        key = f"{pc.get('community','')}-{pc.get('area',0)}"
        price_change_map[key] = pc

    for idx, (community_name, community_data) in enumerate(data.get("communities", {}).items()):
        color = badge_colors[idx % len(badge_colors)]
        icon = community_icons[idx] if idx < len(community_icons) else f"⑥"
        count = community_data.get("count", 0)
        filter_desc = community_data.get("filter", "")

        html += f"""
        <div class="section">
            <div class="section-header">
                <span class="section-title">{icon} {community_name}</span>
                <span class="section-badge {color}">符合 {count} 套</span>
            </div>
            <div class="filter-info">
                📋 筛选条件：{filter_desc}
            </div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>序号</th>
                            <th>小区名称</th>
                            <th>房型</th>
                            <th>建筑面积</th>
                            <th>朝向</th>
                            <th>单价(元/㎡)</th>
                            <th>总价(万)</th>
                            <th>楼层</th>
                            <th>房屋年限</th>
                            <th>挂牌时间</th>
                        </tr>
                    </thead>
                    <tbody>
"""

        if not community_data.get("listings"):
            html += """
                        <tr>
                            <td colspan="10" class="no-data">
                                <div class="icon">📭</div>
                                暂无符合条件的房源
                            </td>
                        </tr>
"""
        else:
            for i, listing in enumerate(community_data["listings"], 1):
                layout = listing.get("layout", "")
                tag_class = "tag-3room" if "3室" in layout else ("tag-1room" if "1室" in layout else "tag-2room")

                # 判断是否为新上线房源
                listing_key = f"{listing.get('community','')}-{listing.get('area',0)}-{listing.get('total_price',0)}"
                row_class = ""
                prefix = ""
                if listing_key in new_listing_ids:
                    row_class = ' class="change-new"'
                    prefix = "🆕 "

                # 判断是否有价格变动
                price_key = f"{listing.get('community','')}-{listing.get('area',0)}"
                price_note = ""
                if price_key in price_change_map:
                    pc = price_change_map[price_key]
                    diff = pc.get("new_price", 0) - pc.get("old_price", 0)
                    if diff < 0:
                        row_class = ' class="change-price-down"'
                        price_note = f" ↓{abs(int(diff))}万"
                    elif diff > 0:
                        row_class = ' class="change-price-up"'
                        price_note = f" ↑{int(diff)}万"

                area_display = f"{listing.get('area', '-')}㎡" if listing.get('area') else "-"
                unit_price_display = format_number(listing.get("unit_price", 0)) if listing.get("unit_price") else "-"
                total_price = listing.get("total_price", 0)

                html += f"""
                        <tr{row_class}>
                            <td>{prefix}{i}</td>
                            <td>{listing.get('community', '')}</td>
                            <td><span class="tag {tag_class}">{layout}</span></td>
                            <td>{area_display}</td>
                            <td>{listing.get('direction', '-')}</td>
                            <td class="price-unit">{unit_price_display}</td>
                            <td class="price-total">{int(total_price)}万{price_note}</td>
                            <td>{listing.get('floor', '-')}</td>
                            <td>{listing.get('age', '-')}</td>
                            <td>{listing.get('listing_date', '-')}</td>
                        </tr>
"""

        html += """
                    </tbody>
                </table>
            </div>
        </div>
"""

    # 条件接近的房源
    nearby = data.get("nearby_listings", [])
    if nearby:
        html += """
        <div class="section">
            <div class="section-header">
                <span class="section-title">📌 其他值得关注的房源（条件接近）</span>
                <span class="section-badge purple">参考</span>
            </div>
            <div class="filter-info">
                以下房源虽略超出筛选条件（总价略超550万或面积略不足），但值得关注
            </div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>序号</th>
                            <th>小区名称</th>
                            <th>房型</th>
                            <th>建筑面积</th>
                            <th>朝向</th>
                            <th>单价(元/㎡)</th>
                            <th>总价(万)</th>
                            <th>楼层</th>
                            <th>说明</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        for i, nl in enumerate(nearby, 1):
            layout = nl.get("layout", "")
            tag_class = "tag-3room" if "3室" in layout else ("tag-1room" if "1室" in layout else "tag-2room")
            area_display = f"{nl.get('area', '-')}㎡" if nl.get('area') else "-"
            unit_price_display = format_number(nl.get("unit_price", 0)) if nl.get("unit_price") else "-"

            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{nl.get('community', '')}</td>
                            <td><span class="tag {tag_class}">{layout}</span></td>
                            <td>{area_display}</td>
                            <td>{nl.get('direction', '-')}</td>
                            <td class="price-unit">{unit_price_display}</td>
                            <td class="price-total">{int(nl.get('total_price', 0))}万</td>
                            <td>{nl.get('floor', '-')}</td>
                            <td>{nl.get('note', '')}</td>
                        </tr>
"""
        html += """
                    </tbody>
                </table>
            </div>
        </div>
"""

    # 说明和注意事项
    html += """
        <div class="notes">
            <h3>📝 说明与注意事项</h3>
            <ul>
                <li><strong>数据来源</strong>：本报告数据综合自链家网、安居客等渠道，由 GitHub Actions 每日自动采集更新。</li>
                <li><strong>采集频率</strong>：每天北京时间 9:00 自动运行，数据通过 GitHub Pages 自动发布。</li>
                <li><strong>价格说明</strong>：以上价格均为挂牌价，实际成交价通常有5-10%的议价空间。</li>
                <li><strong>数据准确性</strong>：房源信息实时变动，以上数据仅供参考，建议以链家APP最新数据为准。</li>
                <li><strong>历史数据</strong>：所有历史采集数据保存在 data_history 目录中，可随时回溯查看。</li>
            </ul>
        </div>
"""

    # 页脚
    gen_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    html += f"""
        <div class="data-source">
            报告自动生成时间：{gen_time} | 数据来源：{source}<br>
            由 GitHub Actions 自动采集 · GitHub Pages 自动发布<br>
            ⚠️ 房源信息实时变动，以上数据仅供参考
        </div>
    </div>
</body>
</html>
"""

    return html


def _generate_changes_section(changes, date_display, data):
    """生成今日变化区块"""
    new_count = changes.get("new_count", 0)
    removed_count = changes.get("removed_count", 0)
    price_change_count = changes.get("price_change_count", 0)
    has_changes = new_count > 0 or removed_count > 0 or price_change_count > 0

    html = f"""
        <div class="section" style="border-left: 4px solid #4caf50;">
            <div class="section-header">
                <span class="section-title">📋 今日变化（{date_display}）</span>
            </div>
"""

    if not has_changes:
        html += f"""
            <div style="padding: 16px; background: #e8f5e9; border-radius: 8px;">
                <p style="font-size: 15px; color: #2e7d32; font-weight: 600; margin-bottom: 8px;">✅ 今日无重大变化</p>
                <ul style="font-size: 14px; color: #555; padding-left: 20px; line-height: 2;">
                    <li>符合条件房源总数保持 <strong>{data.get('total_qualified', 0)}套</strong></li>
                    <li>未发现新上线或下线的符合条件房源</li>
                    <li>未发现价格变动</li>
                </ul>
            </div>
"""
    else:
        html += """
            <div style="padding: 16px; background: #fff3e0; border-radius: 8px;">
                <p style="font-size: 15px; color: #e65100; font-weight: 600; margin-bottom: 8px;">🔔 今日有变化</p>
                <ul style="font-size: 14px; color: #555; padding-left: 20px; line-height: 2;">
"""
        if new_count > 0:
            html += f'                    <li>🆕 <strong>新上线 {new_count} 套</strong>：'
            for nl in changes.get("new_listings", []):
                html += f'{nl.get("community","")} {nl.get("layout","")} {nl.get("area","")}㎡ / {int(nl.get("total_price",0))}万; '
            html += '</li>\n'

        if removed_count > 0:
            html += f'                    <li>❌ <strong>已下线 {removed_count} 套</strong>：'
            for rl in changes.get("removed_listings", []):
                html += f'{rl.get("community","")} {rl.get("layout","")} {rl.get("area","")}㎡ / {int(rl.get("total_price",0))}万; '
            html += '</li>\n'

        if price_change_count > 0:
            html += f'                    <li>💰 <strong>价格变动 {price_change_count} 套</strong>：'
            for pc in changes.get("price_changes", []):
                diff = pc.get("new_price", 0) - pc.get("old_price", 0)
                arrow = "↑" if diff > 0 else "↓"
                html += f'{pc.get("community","")} {pc.get("area","")}㎡: {int(pc.get("old_price",0))}万→{int(pc.get("new_price",0))}万({arrow}{abs(int(diff))}万); '
            html += '</li>\n'

        html += """
                </ul>
            </div>
"""

    html += "        </div>\n"
    return html


def main():
    print("🏠 生成 HTML 监控报告...")

    # 获取最新数据
    latest_file = get_latest_data_file()
    if not latest_file:
        print("❌ 没有找到数据文件，请先运行 scraper.py")
        return

    print(f"  📄 使用数据: {latest_file}")

    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 生成HTML
    html = generate_html(data)

    # 写入文件（同时生成 index.html 用于 GitHub Pages）
    output_file = "index.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 报告已生成: {output_file}")

    # 同时更新根目录的中文名文件（向后兼容）
    compat_file = "北京购房监控_链家数据.html"
    with open(compat_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 兼容文件已更新: {compat_file}")


if __name__ == "__main__":
    main()
