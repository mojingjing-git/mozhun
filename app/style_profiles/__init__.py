"""v4.1.7 风格 Profile 系统 (Style Fingerprint).

借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
借鉴内容: 9 轴风格指纹 (句子节奏/段落/词汇/语气/论证/比喻/情绪/起收/雷区) +
         事实骨架纪律 + AI 6 处易露馅 + 8 轴自评 + 蒸馏流程 (样本 → Style Card)
借鉴方式: 思路借鉴, 无代码复制, 9 轴描述/prompt 措辞全部项目语言重写
Copyright (c) 2026 Jianshuo Wang

模块结构:
- loader.py: StyleProfileLoader (CRUD + 蒸馏入口)
- builtin/*.json: 3 套抽象化预置 profile (无具体真人作家)
"""
