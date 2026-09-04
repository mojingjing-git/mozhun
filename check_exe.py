"""检查打包后的 exe 是否包含 web/ 前端资源 + style_profiles builtin JSON.

v4.1.8.1 (审计修复 D1/D2):
- 路径锚定: 不再依赖 cwd, 用脚本所在目录定位 dist/新时代校对大师.exe
- 分隔符: PyInstaller 在 Windows 上 CArchive 资源路径用反斜杠 (web\\index.html),
  源码里只查 b"web/" 恒匹配 0 次 -> 误报"资源未打入". 现在两种分隔符都查.
- 校验项更新: 移除已不存在的 marked.min.js (web/lib 现在只剩 diff-match-patch.js),
  新增 diff-match-patch.js 与 style_profiles/builtin/*.json 校验 (D2 修复的配套验证).
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
exe_path = os.path.join(BASE_DIR, "dist", "新时代校对大师.exe")
if not os.path.exists(exe_path):
    print(f"ERROR: {exe_path} not found")
    sys.exit(1)

size = os.path.getsize(exe_path)
print(f"EXE size: {size} bytes = {size/1024/1024:.2f} MB")

# 简单方法: 扫描文件中是否含资源路径字符串
with open(exe_path, "rb") as f:
    data = f.read()


def count(sub: bytes) -> int:
    return data.count(sub)


web_fwd = count(b"web/")            # 源码正斜杠写法 (个别 PyInstaller 版本可能存这种)
web_bwd = count(b"web\\")           # Windows 反斜杠写法 (PyInstaller Windows 实际存储)
index_html_count = count(b"index.html")
style_css_count = count(b"style.css")
app_js_count = count(b"app.js")
diff_match_count = count(b"diff-match-patch.js")  # v4.1.8.1: 替代已删除的 marked.min.js
builtin_plain_count = count(b"plain_tech.json")
builtin_narrative_count = count(b"narrative_general.json")
builtin_daily_count = count(b"daily_colloquial.json")

print("字节序列出现次数:")
print(f"  'web/' (正斜杠):            {web_fwd}")
print(f"  'web\\' (反斜杠):           {web_bwd}")
print(f"  'index.html':              {index_html_count}")
print(f"  'style.css':               {style_css_count}")
print(f"  'app.js':                  {app_js_count}")
print(f"  'diff-match-patch.js':     {diff_match_count}")
print(f"  'plain_tech.json':         {builtin_plain_count}")
print(f"  'narrative_general.json':  {builtin_narrative_count}")
print(f"  'daily_colloquial.json':   {builtin_daily_count}")

missing = []
if web_fwd <= 0 and web_bwd <= 0:
    missing.append("web/ 资源目录路径")
if index_html_count <= 0:
    missing.append("index.html")
if style_css_count <= 0:
    missing.append("style.css")
if app_js_count <= 0:
    missing.append("app.js")
if diff_match_count <= 0:
    missing.append("diff-match-patch.js")
if builtin_plain_count <= 0 or builtin_narrative_count <= 0 or builtin_daily_count <= 0:
    missing.append("style_profiles/builtin JSON (D2)")

if not missing:
    print("\n✅ web/ 资源 + style_profiles builtin 已正确打入 exe")
    sys.exit(0)
else:
    print("\n❌ 下列资源可能未打入: " + ", ".join(missing))
    sys.exit(1)
