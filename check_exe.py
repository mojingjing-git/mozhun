"""检查打包后的 exe 是否包含 web/ 资源 (用 PyInstaller 自带工具)."""
import os
import sys
import struct

exe_path = "dist/新时代校对大师.exe"
if not os.path.exists(exe_path):
    print(f"ERROR: {exe_path} not found")
    sys.exit(1)

size = os.path.getsize(exe_path)
print(f"EXE size: {size} bytes = {size/1024/1024:.2f} MB")

# 简单方法: 扫描文件中是否含 web/ 路径字符串
with open(exe_path, "rb") as f:
    data = f.read()

# 找 web/ 出现的字节位置
web_count = data.count(b"web/")
index_html_count = data.count(b"index.html")
style_css_count = data.count(b"style.css")
app_js_count = data.count(b"app.js")
sparkle_svg_count = data.count(b"sparkle.svg")
diff_match_count = data.count(b"diff-match-patch")
marked_count = data.count(b"marked.min.js")

print(f"字节序列出现次数:")
print(f"  'web/':           {web_count}")
print(f"  'index.html':     {index_html_count}")
print(f"  'style.css':      {style_css_count}")
print(f"  'app.js':         {app_js_count}")
print(f"  'sparkle.svg':    {sparkle_svg_count}")
print(f"  'diff-match-patch': {diff_match_count}")
print(f"  'marked.min.js':  {marked_count}")

if web_count > 0 and index_html_count > 0 and style_css_count > 0 and app_js_count > 0:
    print("\n✅ web/ 资源已正确打入 exe")
    sys.exit(0)
else:
    print("\n❌ web/ 资源可能未打入")
    sys.exit(1)
