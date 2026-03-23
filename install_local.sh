#!/bin/bash
# ============================================================
# 北京二手房监控 - 本地定时任务安装脚本
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.yangfei.house-monitor.plist"
PLIST_SRC="${SCRIPT_DIR}/${PLIST_NAME}"
PLIST_DST="${HOME}/Library/LaunchAgents/${PLIST_NAME}"

echo "================================================"
echo "🏠 北京二手房监控 - 本地定时任务安装"
echo "================================================"
echo ""

# 1. 检查 Python 和 Playwright
echo "🔍 检查环境..."
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3"
    exit 1
fi
echo "  ✅ Python: $(python3 --version)"

python3 -c "import playwright" 2>/dev/null || {
    echo "❌ 未安装 playwright，正在安装..."
    pip3 install playwright playwright-stealth
    playwright install chrome
}
echo "  ✅ Playwright 已安装"

if ! command -v git &>/dev/null; then
    echo "❌ 未找到 git"
    exit 1
fi
echo "  ✅ Git: $(git --version)"
echo ""

# 2. 卸载旧任务（如果有）
if launchctl list 2>/dev/null | grep -q "com.yangfei.house-monitor"; then
    echo "🔄 卸载旧的定时任务..."
    launchctl unload "${PLIST_DST}" 2>/dev/null || true
fi

# 3. 复制 plist 到 LaunchAgents
echo "📋 安装定时任务..."
mkdir -p "${HOME}/Library/LaunchAgents"
cp "${PLIST_SRC}" "${PLIST_DST}"
echo "  复制到: ${PLIST_DST}"

# 4. 加载定时任务
launchctl load "${PLIST_DST}"
echo "  ✅ 定时任务已加载"

# 5. 验证
echo ""
echo "🔍 验证安装..."
if launchctl list 2>/dev/null | grep -q "com.yangfei.house-monitor"; then
    echo "  ✅ 定时任务运行中"
else
    echo "  ⚠️  定时任务可能未成功加载，请检查"
fi

echo ""
echo "================================================"
echo "✅ 安装完成！"
echo ""
echo "📋 配置信息："
echo "  采集脚本: ${SCRIPT_DIR}/local_scraper.py"
echo "  运行时间: 每天 09:00"
echo "  日志文件: ${SCRIPT_DIR}/scraper.log"
echo "  launchd日志: ${SCRIPT_DIR}/launchd_stdout.log"
echo ""
echo "📋 常用命令："
echo "  手动运行:     python3 ${SCRIPT_DIR}/local_scraper.py"
echo "  首次验证:     python3 ${SCRIPT_DIR}/local_scraper.py --setup"
echo "  查看日志:     tail -f ${SCRIPT_DIR}/scraper.log"
echo "  卸载定时任务: launchctl unload ${PLIST_DST}"
echo "  重装定时任务: launchctl load ${PLIST_DST}"
echo "================================================"
echo ""

# 6. 提示首次验证
if [ ! -d "${HOME}/.lianjia_monitor_chrome_profile" ]; then
    echo "⚠️  检测到尚未进行首次验证！"
    echo "   请先运行以下命令完成一次验证码验证："
    echo ""
    echo "   python3 ${SCRIPT_DIR}/local_scraper.py --setup"
    echo ""
fi
