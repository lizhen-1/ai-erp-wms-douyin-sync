# ERP/WMS + 多抖店同步原型

这是一个面向自研 ERP/WMS 的首期 Python 原型，用来把核心业务链路先跑通，并为后续团队协作、系统拆分、接口落地提供统一样板。

当前原型重点不是做完整生产系统，而是先把两条主线打通：

1. 商品/库存主数据与多抖店自动建品同步
2. 订单核对、出库、发货、状态回传链路

## 当前业务范围

原型已覆盖这些核心能力：

- 统一主 SKU 管理
- 店铺 SKU 映射
- 商品入库前筛选
- 默认定价
- 店铺级价格覆盖
- 入库审核与库存记账
- 多店铺商品同步
- 同步失败异常任务
- 统一订单池
- AI 辅助核对建议
- 发货扣减库存
- 售罄后多店联动下架
- 审计日志

## 项目结构

- `erp_wms/models.py`
  核心领域模型与状态枚举。
- `erp_wms/repository.py`
  仓储实现，当前包含 `InMemoryRepository` 和 `SQLiteRepository`。
- `erp_wms/services.py`
  首期业务服务，封装建品、入库、同步、抓单、发货、回传等流程。
- `erp_wms/demo.py`
  可直接运行的演示入口，支持 JSON 和 SQLite 两种状态存储方式。
- `tests/test_workflows.py`
  核心链路回归测试。

## 当前仓储模式

### 1. JSON 原型模式

适合：

- 快速演示
- 查看完整状态快照
- 手工比对数据结构

特点：

- 状态保存为 JSON 文件
- 便于阅读和调试
- 更接近“业务样机”

### 2. SQLite 原型模式

适合：

- 模拟后续真实持久化
- 验证状态恢复和续跑
- 为后续接口化、服务化做准备

特点：

- 状态保存到本地 `.db` 文件
- 服务操作后自动提交
- 更接近“可持续试跑”的原型环境

## 运行方式

### 运行演示脚本

JSON 模式：

```bash
python -m erp_wms.demo --backend json --reset
```

SQLite 模式：

```bash
python -m erp_wms.demo --backend sqlite --reset
```

### 指定状态文件

JSON：

```bash
python -m erp_wms.demo --backend json --state-file sample_data/demo-state.json
```

SQLite：

```bash
python -m erp_wms.demo --backend sqlite --state-file sample_data/demo-state.db
```

### 说明

- 不加 `--reset` 时，如果状态文件已存在，会自动从上次状态继续运行。
- 加 `--reset` 时，会忽略旧状态并重新生成演示数据。
- 默认情况下：
  `json` 使用 `sample_data/demo-state.json`
  `sqlite` 使用 `sample_data/demo-state.db`

## 命令行操作

当前原型还提供了一个最小 CLI，可直接对 JSON 或 SQLite 状态库执行业务动作。

### 查看当前状态

```bash
python -m erp_wms.cli --backend sqlite snapshot
```

### 初始化演示数据

```bash
python -m erp_wms.cli --backend sqlite --reset bootstrap-demo
```

### 创建商品

```bash
python -m erp_wms.cli --backend sqlite create-product \
  --master-sku MSKU-001 \
  --name "Basic Tee" \
  --specification "black / L" \
  --attribute category=tee \
  --attribute material=cotton
```

### 商品审核与入库

```bash
python -m erp_wms.cli --backend sqlite screen-product \
  --master-sku MSKU-001 \
  --can-list true \
  --rule-note "approved for launch"

python -m erp_wms.cli --backend sqlite set-price \
  --master-sku MSKU-001 \
  --cost-price 20 \
  --pricing-factor 3

python -m erp_wms.cli --backend sqlite approve-inbound \
  --master-sku MSKU-001 \
  --quantity 5 \
  --cost-price 20 \
  --pricing-factor 3
```

### 多店同步与店铺改价

```bash
python -m erp_wms.cli --backend sqlite sync-shops \
  --master-sku MSKU-001 \
  --shop douyin-a \
  --shop douyin-b

python -m erp_wms.cli --backend sqlite set-shop-price \
  --master-sku MSKU-001 \
  --shop-id douyin-b \
  --price 79
```

### 抓单、发货、回传

```bash
python -m erp_wms.cli --backend sqlite capture-order \
  --source douyin \
  --source-order-id DY-1001 \
  --master-sku MSKU-001 \
  --quantity 1 \
  --receiver-name Alice \
  --address "Shanghai Pudong Test Road 18"

python -m erp_wms.cli --backend sqlite ship-order \
  --order-id ord-00012 \
  --carrier SF \
  --tracking-no SF123456

python -m erp_wms.cli --backend sqlite report-order \
  --order-id ord-00012
```

### CLI 说明

- CLI 默认后端为 `sqlite`
- 可用 `--state-file` 指向指定状态文件
- 每次命令执行后会自动保存当前状态
- 更适合日常试跑和业务链路演示

## 运行测试

```bash
python -m unittest discover -s tests -v
```

当前测试覆盖：

- 入库、定价、同步
- 部分同步失败异常
- 缺地址订单异常
- 发货扣减库存与售罄下架
- JSON 快照恢复
- JSON 文件持久化与续跑
- demo 种子数据防重复灌入
- SQLite 持久化与状态恢复
- CLI 驱动的 SQLite 工作流

## 现阶段定位

这个仓库当前适合作为：

- 业务规则对齐原型
- 后端接口设计前的行为样本
- 团队讨论主 SKU、订单池、库存联动时的共同参考
- 新旧系统并行阶段的流程试验田

它暂时还不是：

- 生产可用 ERP/WMS
- 完整数据库设计
- 完整 API 服务
- 正式任务调度系统
- 正式前端工作台

## 建议的下一步

按当前项目节奏，比较顺的推进顺序是：

1. 基于 SQLite 仓储继续补最小 CLI 或 API 层
2. 明确商品、库存、订单、发货四类核心表结构
3. 把抖店网关从 mock 替换成真实接口适配层
4. 把 AI 核对建议接到真实 LLM 或规则引擎
5. 再逐步拆成后端服务、任务调度和前端工作台
