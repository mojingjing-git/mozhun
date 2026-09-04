# -*- mode: python ; coding: utf-8 -*-
# v4.0+ PyInstaller 打包配置
# 输出: dist/新时代校对大师.exe (onefile, windowed)
# 目标: < 80 MB

block_cipher = None

# 收集 pywebview 在 Windows 上需要的所有隐藏 import
# 借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause) 官方打包说明
# v4.1 (I9): 加 comtypes (webview.edgechromium 依赖), webview.dom + webview.platforms.mshtml
hiddenimports = [
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'webview.platforms.mshtml',   # v4.1 I9
    'webview.dom',                # v4.1 I9
    'comtypes',                   # v4.1 I9: webview.edgechromium 调 webview2 需 comtypes
    'clr_loader',
    'pythonnet',
    'openai',
    'openai.resources',
    'openai.lib',
    'requests',
    # 业务层
    'app',
    'app.processor',
    'app.context_builder',
    'app.utils',
    'app.templates',
    'app.logger',
    'app.web_backend',
]

# 排除 GUI 冲突 / 减重
excludes = [
    'tkinter',
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6_Addons',
    'PySide6_Essentials',
    'qasync',
    'PyQt5',
    'PyQt6',
    'unittest',
    'pytest',
    'IPython',
    'jupyter',
    'notebook',
    'matplotlib',
    'numpy.tests',
    'scipy',
    'pandas',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 整个 web/ 前端资源打包到 exe 内部
        ('web', 'web'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='新时代校对大师',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # v4.1 I11: 关闭 UPX. 杀软 (Windows Defender / 360 / 火绒) 对 UPX 压缩过的 .exe 经常误报
                        #             实际没什么收益, exe 大 2-3 MB 而已, 但误报代价高.
    upx_exclude=[
        # 排除掉无法压缩的 .pyd / .dll（pythonnet / clr_loader 依赖）
        'python*.dll',
        'clr*.dll',
        'pythonnet*.dll',
        'Microsoft.*.dll',
        '*.pyd',
    ],
    runtime_tmpdir=None,
    console=False,      # 窗口模式，无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='app.ico',  # 当前无 .ico，留空用系统默认
)
