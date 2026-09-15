# 坡地菜畦重力灌水换口台

面向用**高位蓄水池 + 软管轮灌坡地菜畦**的家庭种植者。把"预充主管 → 开上游畦口 →
确认水头到尾 → 关旧口 → 移管 → 开新口"的换口顺序编成可逐步确认的作业单，
避免换口失序造成的**上畦漫溢、下畦断流**。

- 前端：React + TypeScript + Vite + SVG（地块绘制与作业高亮）
- 后端：Python FastAPI + SQLite（地块、规则、现场进度持久化）
- 全部本机原生运行，无需外部服务

## 功能

**地块编辑（SVG 画布）**
- 绘制水池、主管/分支管段、分支阀、畦口、畦沟（含落差）、禁踩通道
- 录入管段容量与允许流量、畦沟润湿时长上下限、阀门可达侧、可携管件（软管长度/数量）
- 布局校验：逆坡、畦口不低于水池、沟尾高于沟首、不连通等即时告警

**作业编排（后端规则引擎）**
- 自动生成完整换口顺序，高畦口（上游）先灌
- **R1** 同一分支换口必须先关旧口再开新口（同时只有一个畦口过水）
- **R2** 未到最短润湿时间不得确认"水头到尾"，未确认到尾不得完成该畦
- **R3** 开启低位畦口前，上游空管必须先预充，防止空管倒吸
- **R4** 携管路线不得跨越正在过水（含退水中）的畦沟与禁踩区；自动规划
  直线/L 形绕行，均不可行时给出告警，可在图上自绘绕行路线后放行
- 页面逐步高亮：当前阀门（绿色脉冲）、软管去向（紫色虚线）、观察沟段（蓝色脉冲）
- 堵沟 / 漏接 / 水未到尾：一键上报，从最近确认状态重排未完成畦，
  **已浇畦保留**，漏接会强制重新预充主管
- 误确认可**逐级撤回**（快照恢复）；到尾计时条提示最短/最长润湿窗口

## 运行

```bash
# 后端（Python 3.10+）
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 前端开发（另开终端，代理 /api 到 8000）
cd frontend
npm install
npm run dev        # http://localhost:5173

# 或生产模式：构建后由 FastAPI 直接托管
npm run build      # 然后访问 http://localhost:8000
```

首次使用：地块编辑页点 **载入示例地块**（或 `POST /api/demo/seed`），
切到"灌水作业"页开始作业。

## 测试

```bash
cd backend && python3 -m pytest tests/ -q     # 规则与重排冒烟测试
cd frontend && npm run build                  # 前端类型检查 + 构建
```

## 目录

```
backend/
  app/
    main.py            FastAPI 入口（API + 静态托管）
    db.py              SQLite 连接与建表
    models.py          请求模型
    planner.py         顺序编排、路线几何、布局校验（R1–R4）
    routes_layout.py   布局读写、示例地块
    routes_session.py  作业会话：确认/异常/撤回/自定义路线
  tests/test_flow.py   端到端规则测试
frontend/
  src/
    App.tsx            模式切换、状态与轮询
    components/Canvas.tsx       SVG 画布（编辑 + 作业高亮 + 路线绘制）
    components/EditPanel.tsx    工具与属性编辑
    components/SessionPanel.tsx 作业步骤、确认、异常、撤回
```

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/PUT | `/api/layout` | 读/写整个地块图（作业中保存保留畦沟进度） |
| POST | `/api/demo/seed` | 载入示例地块 |
| POST | `/api/sessions` | 按当前布局生成作业与步骤 |
| GET | `/api/sessions/active` | 当前作业视图（步骤、高亮、畦沟状态） |
| POST | `/api/sessions/{id}/confirm` | 确认当前步骤（R1–R4 服务端强制） |
| POST | `/api/sessions/{id}/issue` | 上报堵沟/漏接/水未到尾并重排 |
| POST | `/api/sessions/{id}/undo` | 撤回最近一次确认或异常上报 |
| POST | `/api/sessions/{id}/steps/{sid}/route` | 自定义移管绕行路线 |
