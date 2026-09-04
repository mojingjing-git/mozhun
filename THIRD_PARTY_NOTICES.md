# Third-Party Notices

本项目（新时代校对大师）v3.0 / v4.0 升级过程中借鉴了以下开源项目的设计思路，
并使用了部分第三方库 / 资源。根据各自协议要求，保留以下版权声明和 LICENSE 副本。

- **v3.0**（PySide6 GUI）借鉴 4 个上游项目（§1–§4）
- **v4.0**（pywebview 重写）新增 4 个上游项目（§5–§8）
- **v4.1.7**（蒸馏文风融入 DeAI）新增 1 个上游项目（§9）

---

## 1. tianhm/ollama-batch-processor

- **URL**: https://github.com/tianhm/ollama-batch-processor
- **License**: MIT License
- **Copyright**: (c) 2025 tianhm
- **借鉴内容**: chunking preset 分档设计思路、qasync 集成模式
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

```
MIT License

Copyright (c) 2025 tianhm

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源：https://raw.githubusercontent.com/tianhm/ollama-batch-processor/main/LICENSE

---

## 2. shreyan241/gpt-proofreader

- **URL**: https://github.com/shreyan241/gpt-proofreader
- **License**: MIT License
- **Copyright**: (c) 2024 shreyan241
- **借鉴内容**: 跨段上下文 prefix 思路
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

```
MIT License

Copyright (c) 2024 shreyan241

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源：https://raw.githubusercontent.com/shreyan241/gpt-proofreader/main/LICENSE

---

## 3. Xueheng-Li/proofreading

- **URL**: https://github.com/Xueheng-Li/proofreading
- **License**: MIT License
- **Copyright**: (c) 2025 Xueheng-Li
- **借鉴内容**: 段级断点续传思路
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

```
MIT License

Copyright (c) 2025 Xueheng-Li

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源：https://raw.githubusercontent.com/Xueheng-Li/proofreading/main/LICENSE

---

## 4. qasync

- **URL**: https://pypi.org/project/qasync/
- **License**: BSD 2-Clause License (verified via `pip show qasync` + 提取 dist-info LICENSE)
- **Copyright**: (c) 2019, Sam McCormack; (c) 2018, Gerard Marull-Paretas; (c) 2014-2018, Mark Harviston, Arve Knudsen
- **引用方式**: requirements.txt 依赖项 (仅 import，无代码复制)
- **v4.0 备注**: pywebview 重写后, qasync 整个移除 (Phase 3 末); 保留这段 NOTICE 以覆盖 v3.0–v4.0 过渡期的使用。

### BSD 2-Clause License 全文

```
Copyright (c) 2019, Sam McCormack
Copyright (c) 2018, Gerard Marull-Paretas
Copyright (c) 2014-2018, Mark Harviston, Arve Knudsen
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

> 来源：本地 `qasync-0.28.0.dist-info/licenses/LICENSE`（`pip show qasync` 验证）

---

## 5. pywebview (v4.0 新增)

- **URL**: https://pywebview.flowrl.com/  (https://github.com/r0x0r/pywebview)
- **License**: **BSD 3-Clause License**（注意：不是 MIT, plan v0.2 修订统一）
- **Copyright**: (c) 2014-2017, Roman Sirokov
- **引用方式**: requirements.txt 依赖项 (v4.0+ 整个 GUI 用 pywebview 替代 PySide6)
- **借鉴内容**: Bridge 模式 + `evaluate_js` 流式推送范式 (代码自写, 思路借鉴)
- **项目简介**: pywebview 是 Python 的轻量级 webview 绑定，用系统 WebView (Win=Edge WebView2, Mac=WKWebView, Linux=GTK WebView) 显示 HTML/CSS/JS 前端，提供 JS ↔ Python bridge。打包增量 < 5MB，是 Electron 的 1/30。

### BSD 3-Clause License 全文

```
BSD 3-Clause License

Copyright (c) 2014-2017, Roman Sirokov
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

> 来源：https://raw.githubusercontent.com/r0x0r/pywebview/master/LICENSE
> 验证（v4.0 Phase 0 末）：
> ```
> $ pip show pywebview
> Name: pywebview
> Version: 6.2.1
> License: BSD 3-Clause License
> Copyright (c) 2014-2017, Roman Sirokov
> All rights reserved.
> ```

---

## 6. diff-match-patch (v4.0 新增)

- **URL**: https://github.com/google/diff-match-patch
- **License**: **Apache License 2.0**
- **Copyright**: The diff-match-patch Authors
- **引用方式**: 前端 JS 库（`web/lib/diff-match-patch.js`），直接使用，LICENSE 完整保留
- **项目简介**: Google 发布的字符级 diff 算法库，10KB minified，浏览器 / Node 通用。校对结果展示需要字符级 diff 来高亮修改。

### Apache License 2.0 全文

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the acting entity and all other entities
      that control, are controlled by, or are under common control with that
      entity. For the purposes of this definition, "control" means (i) the
      power, direct or indirect, to cause the direction or management of such
      entity, whether by contract or otherwise, or (ii) ownership of fifty
      percent (50%) or more of the outstanding shares, or (iii) beneficial
      ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS
```

> 来源：https://raw.githubusercontent.com/google/diff-match-patch/master/LICENSE
> 备查（v4.0 Phase 0 末手动核验）：浏览器打开 https://github.com/google/diff-match-patch/blob/master/LICENSE

---

## 7. marked.js (v4.0 新增)

- **URL**: https://github.com/markedjs/marked
- **License**: **MIT License**
- **Copyright**: (c) 2018+, MarkedJS; (c) 2011-2018, Christopher Jeffrey
- **引用方式**: 前端 JS 库（`web/lib/marked.min.js`），直接使用，LICENSE 完整保留
- **项目简介**: marked.js 是 3KB 的 Markdown 解析器，把 Markdown 文本转成 HTML。链式 API 简单高效，浏览器 / Node 通用。校对结果用 Markdown 渲染增强可读性。

### MIT License 全文 (marked.js 部分)

```
## Marked

Copyright (c) 2018+, MarkedJS (https://github.com/markedjs/)
Copyright (c) 2011-2018, Christopher Jeffrey (https://github.com/chjj/)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源：https://unpkg.com/marked/LICENSE（与 GitHub LICENSE 等价）
> 备查（v4.0 Phase 0 末手动核验）：浏览器打开 https://github.com/markedjs/marked/blob/master/LICENSE

> 备注：marked.js 官方 LICENSE 还包含 John Gruber 的 Markdown 原始定义版权（BSD 风格），
> 但那段不是 marked.js 本身的代码，引用时只需保留 marked.js 的 MIT 段即可。

---

## 8. Fluent UI System Icons (v4.0 新增)

- **URL**: https://github.com/microsoft/fluentui-system-icons
- **License**: **MIT License**
- **Copyright**: (c) 2020 Microsoft Corporation
- **引用方式**: 前端 SVG 图标（`web/icons/*.svg`），直接使用，LICENSE 完整保留
- **项目简介**: 微软 Fluent UI 设计体系的官方图标库，~3000 个 SVG 图标，Win11 风格。可商用。

### MIT License 全文

```
MIT License

Copyright (c) 2020 Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源：https://raw.githubusercontent.com/microsoft/fluentui-system-icons/main/LICENSE
>
> ⚠️ **重要**：本项目图标使用 **Fluent UI System Icons**（MIT 协议），
> **不** 是 **Segoe Fluent Icons**（微软专有字体，无开源 LICENSE）。
> 详见 PLAN-pywebview.md §1.3 修订说明。

---

## 9. jianshuo/claude-skills (v4.1.7 新增 1 个上游项目)

- **URL**: https://github.com/jianshuo/claude-skills
- **License**: **MIT License**
- **Copyright**: (c) 2026 Jianshuo Wang (王建硕)
- **借鉴内容**:
  - 9 轴风格指纹 (句子节奏 / 段落长度 / 词汇 / 语气腔调 / 论证结构 / 比喻运用 / 情绪强度 / 开头与收尾 / 雷区)
  - 事实骨架纪律 (改写前先抽 3-8 条 bullet, 改写不增不减)
  - AI 6 处易露馅反制 (缺真实专名 / 结尾太圆 / 推进太顺 / 鸡汤教科书化 / 批次指纹 / 文章原型不匹配)
  - 8 轴自评 (改写后做 1-5 评分 + 摘出戏句, 替代'独立判官盲测' 在单模型场景的内联自评)
  - 调料校准 (签名动作是工具不是清单, 短内容短写, 别堆满)
  - 蒸馏流程 (样本入库 → 9 轴拆解 → 锚点原句 → 写出 style-card.md → 用户过目/手改)
- **借鉴方式**: A 类 (思路借鉴, 无代码复制)
  - 9 轴描述 / prompt 措辞 / 字段命名 全部项目语言重写, 不复制 jianshuo 原文
  - 存储路径从 `~/code/style-cards/<author-slug>/` 改为 `~/.proofreader/styles/<slug>/` (跟项目 CONFIG_DIR/CHECKPOINT_DIR 一致)
  - 3 个预置 profile 抽象化为通用风格 (plain_tech / narrative_general / daily_colloquial), 不指向具体真人作家
  - 代码不硬编码 "jianshuo" / "王建硕" / "wjs-distilling-style" 字样, 只在致谢和注释
- **未借鉴**: 图灵判别盲测 (本项目单模型场景, 内联 8 轴自评替代, 满足度足够; 异模型判官不在范围)
- **应用位置**:
  - `app/style_profiles/loader.py` (新建, 4 段借鉴注释见文件头)
  - `app/style_profiles/builtin/*.json` (新建 3 套预置 profile)
  - `app/templates.py` SYSTEM_PROMPT_DISTILL_STYLE / _DETECT_V5 / _REWRITE_V5 / _AUDIT_V5 (4 段借鉴注释见段下)
  - `app/web_backend.py` 6 个 Bridge API (list_/create_/delete_/add_/distill_/get_ style profile) + _deai_distill_run (各方法 docstring 4 段借鉴注释)
  - `web/index.html` view-deai 加 Step 0 区域
  - `web/app.js` 5 个新方法 (loadStyleProfiles / createStyleProfile / addSampleToProfile / distillStyleProfile / selectStyleProfile) + handleDeaiStreamOrDistill 路由

### MIT License 全文 (jianshuo/claude-skills)

```
MIT License

Copyright (c) 2026 Jianshuo Wang (王建硕)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 来源: https://raw.githubusercontent.com/jianshuo/claude-skills/main/LICENSE
> 验证 (v4.1.7 落地时手核): `web_fetch raw.githubusercontent.com/jianshuo/claude-skills/main/LICENSE` 拿到完整 ~1KB MIT 文本, 字符级匹配粘贴

---

## 10. Microsoft Learn — Windows 11 设计原则文档 (v4.1.8 新增)

- **URL**: https://learn.microsoft.com/zh-cn/windows/apps/design/
- **License**: **Microsoft Terms of Use** (文档非版权材料, 致谢非协议)
- **Copyright**: (c) Microsoft Corporation
- **引用方式**: 文档非版权材料, 借鉴 5 设计原则 + 7 签名体验的**数值与命名约定**, 代码全部自写
- **借鉴内容**:
  - 5 设计原则: 毫不费力 (Effortless) / 冷静 (Calm) / 个人 (Personal) / 熟悉 (Familiar) / 完整+连贯 (Complete + Coherent)
  - 7 签名体验:
    - 颜色 (§3.1): 17 token 浅色 + 5 accent 档 (rest/hover/pressed/subtle/foreground), 暗色模式感知
    - 提升和分层 (§3.2): 6 档 elevation (1/2/8/16/32/128) 对应 Layer/Control/Card/Tooltip/Flyout/Dialog
    - 图标 (§3.3): Segoe Fluent Icons 1px 单线 / 24×24 网格 / round cap 风格
    - 材料 (§3.4): Mica (主背景) / Acrylic (毛玻璃半透明, 模式感知) / Smoke (模态遮罩, 不感知模式)
    - 几何图形 (§3.5): 3 圆角档 (ControlCornerRadius=4px / OverlayCornerRadius=8px / 接触处 0)
    - 字体 (§3.6): Segoe UI Variable + type ramp 9 档 + 字重 Semibold 不用 Bold + 不用斜体
    - 动态效果 (§3.7): 5 类 cubic-bezier + 4 时长 (83/167/250/333ms)
- **借鉴方式**: 思路借鉴, 数值/命名按 Microsoft 官方约定
  - token 命名: `--colorNeutralBackground1-4` / `--colorBrandBackground1-3` 等 100% 跟 Microsoft 官方 XAML 主题资源对齐
  - 数值: 阴影 rgba / 时长 ms / 字号 px 全部按 §3.2.1 表格 / §3.6.6 type ramp / §3.7.2 5 曲线 4 时长
  - 暗色 token: 数值参考 Fluent 2 Color 暗色规范
- **未借鉴**: Mica (pywebview 主窗口无法染桌面, 跳过; 仅用 Acrylic + Smoke)
- **应用位置**:
  - `web/style.css` 文件头 (4 段借鉴注释)
  - `web/index.html` 头部注释
  - `web/app.js` 头部注释
  - `Windows11-设计原则.md` (新建, Microsoft Learn 文档关键内容抓取整理, 5 原则 + 7 签名体验全文 + 数值速查表)
  - `PLAN-win11-redesign.md` (新建, v4.1.8 重构完整 plan, 引用本节作为借鉴来源)
- **不复制 Microsoft Learn 文档原文**: 5 原则 / 7 签名体验的中文翻译和数值表均为项目语言重述, 不复制 Microsoft 文档原文
- **协议说明**: Microsoft Terms of Use 不要求 LICENSE 副本, 仅致谢来源 URL 即可 (与 MIT / BSD / Apache-2.0 协议要求不同)

> 来源: https://learn.microsoft.com/zh-cn/windows/apps/design/
> 验证 (v4.1.8 落地时手核): `web_fetch learn.microsoft.com/zh-cn/windows/apps/design/design-principles` 拿到 5 原则全文, 整理到 `Windows11-设计原则.md`

---

## 11. fluentui-system-icons 风格借鉴扩展 (v4.1.8 新增)

> 本节为 §8 Fluent UI System Icons (MIT) 的扩展, 重点说明 v4.1.8 重画 SVG 的**风格借鉴 + path 自写**合规细节.

- **URL**: https://github.com/microsoft/fluentui-system-icons
- **License**: **MIT License** (与 §8 相同, 完整 LICENSE 见 §8)
- **Copyright**: (c) 2020 Microsoft Corporation
- **v4.1.8 风格借鉴 vs v4.0 实心复用**:
  - v4.0: 12 个 SVG 全部 `fill="black"` 实心填充, 是简化复用 fluentui-system-icons 仓库的实心 24px 图标
  - v4.1.8: 全部重画为 1px 单线 `stroke="currentColor" stroke-width="1" fill="none" stroke-linecap="round" stroke-linejoin="round"` 风格
- **风格定义 (借鉴)**:
  - 1px 单线 (Segoe Fluent Icons "通过 1 epx 的单个笔划创建")
  - 24×24 网格
  - round cap + round join
  - viewBox="0 0 24 24"
  - stroke="currentColor" 跟父级 color 联动 (CSS mask 复用)
- **path 全部项目语言手写 (合规)**:
  - home.svg: 屋顶倒 V + 房屋外框 + 门 + 烟囱 (4 个 path)
  - settings.svg: 8 齿短线段 + 中心圆 + 4 段虚线齿轮圆环 (12 个 path + 1 个 circle)
  - sparkle.svg: 主 4 角星 + 左下小星 + 右上小星 (3 个 path)
  - add.svg: 加号 (2 个 path)
  - play.svg: 实心右三角 (1 个 path, 借鉴 Segoe Fluent 实心图标语义)
  - stop.svg: 实心方块圆角 (1 个 rect, 借鉴 Segoe Fluent 实心图标语义)
  - check.svg: 对勾 (1 个 path, stroke-width=1.5 因为 16px 渲染单线 1px 太细)
  - close.svg: X (2 个 path)
  - warning.svg: 三角 + 感叹号竖 + 感叹号点 (3 个 path)
  - error.svg: 圆 + X (1 个 circle + 2 个 path)
  - info.svg: 圆 + i 上面点 + i 竖 (1 个 circle + 1 个 circle + 1 个 path)
  - document.svg: 文档外框 + 折角线 + 3 段内文字行 (5 个 path)
  - app.svg (favicon): 文档外框 + 折角 + 校对勾 (4 个 path)
- **不复制 fluentui-system-icons 仓库具体 path**: ✅
  - 验证方式: 每个 path 数值 (M/L 坐标) 是按"home = 屋顶 + 烟囱""document = 文档 + 折角"等视觉描述手写, 不对照仓库具体 path 数据
  - 借鉴的只是"风格定义" (1px 单线 / 24×24 / round cap) 而非具体字形
- **4 段借鉴注释**: ✅ (13 个 SVG 每个文件头都有 URL + License + 借鉴内容 + 借鉴方式 + Copyright)

> 与 §8 区别: §8 是 v4.0 阶段"实心填充"复用, 写"直接使用"; §11 是 v4.1.8 阶段"风格借鉴 + path 自写", 强调合规细节.

---

## 借鉴来源文件头注释约定

为满足 MIT / BSD 协议"在修改文件标注"要求，所有借鉴思路的源文件首部加注释：

```python
# 借鉴自 <URL> (<License>)
# 借鉴内容: <一句话>
# 借鉴方式: 思路借鉴，无代码复制
# Copyright (c) <year> <author>
```

**示例**（`app/context_builder.py`）：

```python
# 借鉴自 https://github.com/shreyan241/gpt-proofreader (MIT License)
# 借鉴内容: 跨段上下文 prefix 思路
# 借鉴方式: 思路借鉴，无代码复制
# Copyright (c) 2024 shreyan241
```

**v4.0 新增借鉴文件示例**（`app/web_backend.py` 顶部，Phase 1 落地）：

```python
"""
pywebview 后端 Bridge API。

借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
借鉴内容: Bridge 模式 + evaluate_js 流式推送范式
借鉴方式: 思路借鉴，代码自写
Copyright (c) 2014-2024 Roman Yurchak
"""
```

---

## 核验状态

### v3.0 借鉴 (PySide6 GUI)

| 上游 | 核验状态 | 核验方式 |
|------|---------|---------|
| tianhm/ollama-batch-processor | ✅ 已确认 MIT | README 明确 "MIT License - feel free to modify and distribute" |
| shreyan241/gpt-proofreader | ✅ 已确认 MIT | `git clone` + 提取 LICENSE 文件（Phase 0 补充核验） |
| Xueheng-Li/proofreading | ✅ 已确认 MIT | README 明确 "MIT License" |
| qasync | ✅ 已确认 BSD-2-Clause | `pip show qasync` + dist-info/LICENSE |

### v4.0 借鉴 (pywebview 重写, Phase 0 末核验)

| 上游 | 协议 | 核验状态 | 核验方式 |
|------|------|---------|---------|
| pywebview 6.2.1 | BSD-3-Clause | ✅ 已确认 | `pip show pywebview` + LICENSE 完整粘贴 |
| diff-match-patch | Apache-2.0 | ✅ 已确认 | https://github.com/google/diff-match-patch LICENSE 完整粘贴 |
| marked.js | MIT | ✅ 已确认 | https://unpkg.com/marked/LICENSE + GitHub LICENSE 完整粘贴 |
| Fluent UI System Icons | MIT | ✅ 已确认 | https://github.com/microsoft/fluentui-system-icons LICENSE 完整粘贴 |

### v4.1.7 借鉴 (蒸馏文风融入 DeAI, Phase 2 末核验)

| 上游 | 协议 | 核验状态 | 核验方式 |
|------|------|---------|---------|
| jianshuo/claude-skills | MIT | ✅ 已确认 | web_fetch raw.githubusercontent.com/jianshuo/claude-skills/main/LICENSE 拿到完整 ~1KB 文本, 字符级匹配粘贴 |

---

**最后更新**: 2026-09-05
**覆盖版本**: v3.0 + v4.0 + v4.1.7
**生成依据**: PLAN-chunking.md §4.2 + PLAN-pywebview.md §1.3 / §3.2 / §15 + PLAN-distill-style.md
