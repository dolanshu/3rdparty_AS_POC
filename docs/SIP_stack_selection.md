# 开源 SIP 协议栈选型对比（与 sippy 对照）

## 基准：sippy 是什么

**sippy**（Sippy Labs / sobomax，BSD-2-Clause）是纯 Python 的 RFC3261 栈 + Back-to-Back User Agent（B2BUA）。

- 与 SIP proxy 不同：proxy 只维持 **transaction state**，sippy 维持 **完整 call state** 并参与所有呼叫请求。因此能做 proxy 做不到的事——精确计费、预付费计费与扣费、failover 路由等。
- 与 Asterisk 这类 PBX 不同：sippy **不做任何媒体中继或处理**，因此不向媒体路径引入额外的丢包、时延或抖动。
- 性能标称：单台 5,000–10,000 并发会话；150–400 call setups/teardowns per second。
- 生态：支持 RFC7118 兼容的 secure websocket（wss）接口接 WebRTC；可配合 **sippy RTPProxy** 做媒体中继；支持 Cisco 兼容的 RADIUS AAA；可与 OpenSIPS / SER 组合成完整 softswitch。
- 另有官方 Go 移植 **`go-b2bua`**。
- 许可：BSD-2-Clause（`b2bua` 仓库）/ BSD（PyPI 上 `sippy` 包标注 BSD）。

> ⚠️ 排除混淆项：**SIPp** 是 SIP 流量发生器 / 压测工具（XML 场景脚本，模拟 UAC/UAS），**不是协议栈**，与 sippy 不是同一类东西。

---

## 分层视角：裸栈 / 服务器平台 / 应用框架

选型先分清这三层，比单纯罗列更能决定方向：

1. **纯信令栈**：库，你自己写业务逻辑（sippy 在这一层）
2. **服务器平台**：成型的服务，用配置或脚本表达路由与业务
3. **应用框架层**：堆栈之上的编程框架，最快出活

---

## 一、纯信令栈（与 sippy 直接对位）

| 栈 | 语言 / 许可 | 核心特点 | 最适合 |
|---|---|---|---|
| **PJSIP** (pjproject) | C / GPLv2 或商业双许可 | 信令 + **媒体**全栈（PJMEDIA 编解码、PJNATH 的 STUN/TURN/ICE）；footprint < 200KB；跨平台到极端程度；通过 SWIG 官方绑定 Python / Java / C# | 需要媒体能力的 UA、嵌入式终端；文档与示例最全 |
| **Sofia-SIP** | C / LGPL | Nokia Research Center 出品，事件驱动，单一 `nua` API；**FreeSWITCH 与 Flexisip 的底层** | 追求 RFC3261 严谨性、纯信令、轻量；缺点：需先吃透 SIP 才能用好 `nua`，门槛高于 DUM |
| **reSIProcate** | C++ / Vovida（类 BSD） | 三层 API（底层 / DUM / recon）；自带 **repro** proxy + registrar + Web 管理；CounterPath 商用产品、Sipwise NGCP 在用 | 服务器端、商业友好许可；注意 TCP/TLS 传输层实现是相对短板 |
| **Belle-SIP** | C / GPLv3 或商业 | Linphone 的信令层；采用 RFC6026 更新版事务状态机；**全异步传输层**（UDP/TCP/TLS + DNS SRV/AAAA）；完整双栈 IPv6；`refresher` 对象提供断网恢复与自动刷新 | 现代 C 项目、移动端；仓库已并入 `linphone-sdk` |
| **libre + baresip** | C / **BSD-3-Clause** | creytiv 血统，异步 I/O、低内存占用；SIP/SDP/RTP/SRTP/STUN-TURN-ICE/WebSocket 全套模块化 | 想避开 GPL 又要工业级质量；2025 仍高频发布（libre 4.3.0 / baresip 4.2+） |
| **oSIP + eXosip2** | C / GPL(eXosip) + LGPL(oSIP) | 最早期的开源栈之一，几百 KB，API 极简 | 学习 / 实验、极小嵌入式；GPL 是商用障碍，活跃度已低 |
| **rsipstack** | **Rust / MIT** | 严格四层架构（transport / transaction / dialog / app）；tokio 异步；UDP/TCP/TLS/WebSocket；内置 digest auth（MD5/SHA-256/SHA-512）与注册刷新 | 用 Rust 写 SBC / proxy / registrar 的新项目 |
| **Doubango** | C / GPLv3 | 唯一按 **3GPP TS 24.229** 实现的 IMS 栈（IMS-AKA、SigComp、IPsec、ENUM、SMS over IP） | ⚠️ **约 2016 年后停止开发**，原厂商转向 AI vision，不建议新项目采用 |

---

## 二、服务器平台（不是裸栈，但可作为 AS 的地基）

- **Kamailio**（C / GPLv2+）：路由引擎。**KEMI 可直接用 Python / Lua / JS / Ruby 写路由逻辑**——做 AS POC 最省力的路径之一。v6.0.0（2025-01）新增五个模块，含多线程 UDP 收包模式、端口范围监听、cmake 构建、http2 客户端/服务端。
- **OpenSIPS**（C / GPL）：与 Kamailio 同源（2008 年从 SER/OpenSER 分裂）不同路。**原生 B2BUA 模块比 Kamailio 完整**，适合计费、动态路由、IMS 组件场景；当前稳定分支 3.6。
- **FreeSWITCH**：B2BUA + 全媒体栈（转码 / IVR / 会议 / 录音 / WebRTC），底层即 Sofia-SIP。
- **Flexisip**（C++20，AGPLv3 或商业许可）：Belledonne 的 proxy + presence + conference + B2BUA 套件，底层是 **fork 过的 Sofia-SIP**（仅加了少量维护补丁）。

> **核心区分**：Kamailio / OpenSIPS 是 **代理**——不碰媒体、拼 CPS；FreeSWITCH / Asterisk 是 **B2BUA**——终结呼叫并锚定媒体。做 AS 时通常是"代理在前扛注册与路由，B2BUA 在后做业务"。

---

## 三、应用框架层（最快出活的 AS 骨架）

- **drachtio**（MIT）：**C++ 的 Sofia 内核（drachtio-server）+ Node.js 框架（drachtio-srf）**。Express 风格中间件 `srf.invite / register / options / subscribe`；一个 `createB2BUA` 直接建立配对的 UAS + UAC 腿，媒体交给 rtpengine。2026 年仍在活跃提交。用 TypeScript 快速验证 AS 逻辑的最快路径。
- **JAIN-SIP**（NIST jsip，public domain）：Java，**JSR-32 参考实现**，Listener/Provider 事件模型，自带 TCK，解析器通过 SIPPING torture tests。但 NIST 明确声明不保证持续支持，定位偏实验性。
- **SIP.js / JsSIP**：浏览器侧，SIP over WebSocket + WebRTC，配合 Kamailio / Asterisk / OverSIP。

---

## 针对 SIP AS POC 的判断

**sippy 本身已经是很对位的选择，不建议更换。** 理由：

1. B2BUA 语义天然就是 AS 的形态——需要维持 call state、改写 SDP、插入业务逻辑；
2. BSD-2 许可干净；
3. Python 让你把精力放在业务逻辑而非协议细节；
4. 不做媒体中继在 POC 阶段反而是优点，需要时按需外挂 sippy RTPProxy 即可。

### 值得考虑切换的三个触发点

| 触发点 | 建议路线 |
|---|---|
| 并发 / CPS 撞墙（sippy 单进程 150–400 CPS） | 直接上官方 `go-b2bua`，同一作者、同一套设计，迁移成本最低 |
| 需要媒体能力（放音、转码、录音、DTMF） | 不要自己接媒体：sippy + RTPProxy，或 Kamailio / OpenSIPS + FreeSWITCH 分层 |
| 要验证 IMS 互操作与合规性 | 用 **SIPp** 压测自己的 AS，配 Kamailio 的 IMS 模块做对比参照 |

### 商用许可红线

若未来要商用落地，注意 copyleft 约束：

- 需注意（GPL / AGPL 或双许可，商用常需购买授权）：**PJSIP**、**Flexisip / Belle-SIP**（GPLv3 / AGPLv3）、**Kamailio**（GPLv2+）、**Sofia-SIP**（LGPL）、**oSIP/eXosip**（GPL）
- 对闭源最友好：**sippy（BSD-2）**、**libre / baresip（BSD-3）**、**reSIProcate**、**rsipstack（MIT）**、**drachtio（MIT）**

---

## 附：待确认的两个决策变量

1. AS 在 IMS 架构中的位置——是 S-CSCF 之后的应用服务器，还是独立前置的 B2BUA？
2. 是否需要处理媒体？

这两个答案直接决定应采用上述哪条路线。
