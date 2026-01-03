# 单进程防护机制

## 概述

为了防止危险的双仓位复制问题，**本程序实现了严格的单进程防护机制**。同时只能运行一个 `copybot` 主进程。

## 核心机制

### 1. 文件锁（File Lock）
- **使用 `fcntl.flock()`** - Unix系统的原子操作文件锁
- **位置**：`logs/multi_trader.lock` 和 `logs/copy_trader.lock`
- **原理**：通过操作系统级别的互斥锁，确保文件只能被一个进程独占打开

### 2. PID 验证
- **文件**：`logs/multi_trader.pid` 或 `logs/copy_trader.pid`
- **功能**：记录当前运行的进程ID
- **自动清理**：如果进程已崩溃，系统会自动清理陈旧的PID文件和锁

### 3. 进程检查
- **使用 `psutil` 库**检查PID文件中记录的进程是否真的在运行
- **防止**：进程异常终止后留下的"僵尸"锁文件

## 工作流程

### 启动时的检查流程

```
用户启动新进程
    ↓
[第1步] 检查是否已有进程运行
    ↓
    ├─ 是 → 检查PID进程是否真的存在
    │   ├─ 存在 → ❌ 拒绝启动，显示错误
    │   └─ 不存在 → 清理陈旧锁文件，继续
    │
    └─ 否 → 继续
    ↓
[第2步] 尝试获取文件锁
    ↓
    ├─ 成功 → ✅ 启动进程，记录PID
    └─ 失败 → ❌ 拒绝启动（有其他进程持有锁）
```

## 使用说明

### 正常启动

```bash
# 启动多钱包跟单
./scripts/manage_multi_trader.sh start

# 或启动单钱包跟单
./scripts/manage_copy_trader.sh start
```

### 启动失败的排查

#### 场景1：提示"已有其他进程在运行"

```bash
❌ 无法启动新进程：已有其他多钱包跟单进程在运行
   请先停止现有进程：./scripts/manage_multi_trader.sh stop
```

**解决方法：**
```bash
# 方法1：正常停止（优先）
./scripts/manage_multi_trader.sh stop

# 方法2：强制停止
pkill -KILL -f "run_multi_trader.py"
```

#### 场景2：进程因故崩溃后，提示"已在运行"

```bash
# 系统会自动检测并清理陈旧的锁文件
# 如果自动清理失败，手动清理：
rm -f logs/multi_trader.lock logs/multi_trader.pid
rm -f logs/copy_trader.lock logs/copy_trader.pid

# 然后重新启动
./scripts/manage_multi_trader.sh start
```

## 核心代码

### 多钱包版本（run_multi_trader.py）

```python
from src.utils.single_instance_lock import SingleInstanceLock

def main():
    # 获取单进程锁
    lock_file = project_root / 'logs' / 'multi_trader.lock'
    lock = SingleInstanceLock(str(lock_file))
    
    # 启动、重启、监控操作时必须持有锁
    if args.action in ['start', 'restart', 'monitor']:
        if not lock.acquire():
            print("❌ 无法启动：已有其他进程运行")
            sys.exit(1)
        
        # 注册清理函数
        atexit.register(lock.release)
```

### 单钱包版本（run_copy_trader.py）

```python
def _acquire_single_instance_lock(project_root: Path) -> int:
    """获取单进程锁"""
    lock_path = project_root / "logs" / "copy_trader.lock"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("❌ Another copy-trader instance is already running.")
        sys.exit(2)
```

## 安全保证

✅ **防止双仓位复制**：任意时刻只有1个主进程 + N个子钱包进程

✅ **自动恢复**：进程崩溃后自动清理锁文件

✅ **原子性**：使用操作系统级文件锁，避免竞态条件

✅ **跨会话有效**：即使SSH连接中断，锁仍然有效

## 监控和调试

### 查看当前进程状态

```bash
# 多钱包
./scripts/manage_multi_trader.sh status

# 单钱包
./scripts/manage_copy_trader.sh status
```

### 查看锁文件内容

```bash
# 查看多钱包锁
cat logs/multi_trader.pid
# 输出示例：12345

# 验证进程是否存在
ps -p 12345
```

### 查看日志

```bash
# 多钱包启动日志
tail -f logs/multi_service_stdout.log

# 子实例日志
tail -f logs/trader_1.log
tail -f logs/trader_2.log

# 单钱包日志
tail -f logs/copy_trader.log
```

## 风险防护清单

| 风险 | 防护机制 | 检查命令 |
|------|--------|---------|
| 双进程同时运行 | fcntl文件锁 | `pgrep -af run_multi_trader` |
| 僵尸锁文件阻止启动 | 自动PID验证和清理 | `cat logs/multi_trader.pid` |
| 进程异常未清理 | atexit清理处理 | `ls -la logs/*.lock` |
| 启动失败不易诊断 | 详细错误日志 | `tail logs/multi_service_stdout.log` |

## 与 Shell 脚本的配合

管理脚本 (`manage_multi_trader.sh`) 的工作流程：

```bash
is_running()          # 检查是否有进程运行
    ↓
start_service()       # 启动monitor进程
    ↓
Python锁获取          # 在run_multi_trader.py中
    ↓
monitor循环           # 监控子实例状态
```

## 常见问题

### Q: 为什么启动脚本比以前慢了？
A: 新增了进程验证步骤。这是为了安全性的必要代价。通常只增加100-200ms。

### Q: 能否同时启动单钱包和多钱包？
A: **不能**。两者共享相同的锁机制。必须先停止一个，再启动另一个。

### Q: 如何确保远程服务器上只有一个进程？
A: 每个实例的锁文件都是独立的，但一个server上的copybot项目只能有一个monitor。

### Q: 锁文件损坏会怎样？
A: 系统会自动检测并删除。如果不行，手动删除后重启：
```bash
rm -f logs/*.lock logs/*.pid
```

---

**版本**: v1.6.2+
**最后更新**: 2026-01-03
