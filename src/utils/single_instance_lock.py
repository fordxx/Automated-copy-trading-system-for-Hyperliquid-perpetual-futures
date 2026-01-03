#!/usr/bin/env python3
"""单进程锁机制 - 确保整个程序同时只有一个进程运行

该模块提供以下功能：
1. 文件锁（fcntl）- Unix系统的原子操作锁
2. PID检查 - 验证PID文件中的进程是否真的在运行
3. 自动清理 - 清理已死亡的进程的锁文件
4. 上下文管理器 - 确保锁在程序退出时被释放
"""
import os
import sys
import signal
import logging
import fcntl
import psutil
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class SingleInstanceLock:
    """单进程锁 - 确保只有一个进程能运行此程序"""
    
    def __init__(self, lock_file: str):
        """初始化锁机制
        
        Args:
            lock_file: 锁文件路径
        """
        self.lock_file = Path(lock_file)
        self.lock_fd = None
        self.pid_file = self.lock_file.parent / (self.lock_file.stem + '.pid')
    
    def _cleanup_stale_lock(self) -> bool:
        """清理已死亡进程留下的锁文件
        
        Returns:
            True 如果成功清理了陈旧的锁，False 否则
        """
        if not self.pid_file.exists():
            return True
        
        try:
            with open(self.pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            
            # 检查进程是否还在运行
            try:
                process = psutil.Process(old_pid)
                # 进程存在，检查是否是我们的程序
                try:
                    cmdline = ' '.join(process.cmdline())
                    if 'run_multi_trader.py' in cmdline or 'run_copy_trader.py' in cmdline:
                        # 进程还在运行且是我们的程序，不能清理
                        return False
                except (psutil.AccessDenied, IndexError):
                    # 无法读取命令行，但进程存在，保险起见不清理
                    return False
            except psutil.NoSuchProcess:
                # 进程不存在，可以清理
                pass
            
            # 进程已死亡，清理锁文件
            logger.warning(f"🧹 清理陈旧锁文件 (PID {old_pid} 已不存在)")
            self.pid_file.unlink(missing_ok=True)
            if self.lock_file.exists():
                self.lock_file.unlink(missing_ok=True)
            return True
            
        except Exception as e:
            logger.error(f"❌ 清理陈旧锁失败: {e}")
            return False
    
    def acquire(self) -> bool:
        """获取锁
        
        Returns:
            True 成功获取锁，False 已有其他进程持有锁
            
        Raises:
            RuntimeError: 如果发生系统错误
        """
        # 确保锁文件目录存在
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 尝试以独占模式打开文件
        try:
            self.lock_fd = open(self.lock_file, 'w')
        except IOError as e:
            raise RuntimeError(f"❌ 无法打开锁文件 {self.lock_file}: {e}")
        
        # 尝试获取独占锁（非阻塞模式）
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # 无法获取锁，说明已有其他进程运行
            self.lock_fd.close()
            self.lock_fd = None
            
            # 尝试读取运行中的进程信息
            try:
                with open(self.pid_file, 'r') as f:
                    other_pid = int(f.read().strip())
                logger.error(f"❌ 已有其他进程在运行 (PID {other_pid})")
                logger.error(f"   请先停止该进程或等待其完成")
            except:
                logger.error(f"❌ 已有其他进程在运行")
                logger.error(f"   请检查锁文件: {self.lock_file}")
            
            return False
        
        # 成功获取锁，写入PID
        try:
            current_pid = os.getpid()
            self.lock_fd.write(f"{current_pid}\n")
            self.lock_fd.flush()
            
            # 同时写入PID文件（备份）
            with open(self.pid_file, 'w') as f:
                f.write(f"{current_pid}\n")
            
            logger.info(f"✅ 成功获取单进程锁 (PID {current_pid})")
            return True
            
        except Exception as e:
            self.release()
            raise RuntimeError(f"❌ 写入PID失败: {e}")
    
    def release(self):
        """释放锁"""
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
            except Exception as e:
                logger.warning(f"⚠️  释放锁失败: {e}")
            finally:
                self.lock_fd = None
            
            # 清理PID文件
            try:
                self.pid_file.unlink(missing_ok=True)
                self.lock_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"⚠️  清理锁文件失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        if not self.acquire():
            raise RuntimeError("❌ 无法获取单进程锁 - 已有其他进程在运行")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()


def setup_single_instance_protection(lock_file: str) -> SingleInstanceLock:
    """设置单进程保护
    
    Args:
        lock_file: 锁文件路径
        
    Returns:
        SingleInstanceLock 实例
        
    Raises:
        RuntimeError: 如果已有其他进程运行
    """
    lock = SingleInstanceLock(lock_file)
    
    if not lock.acquire():
        sys.exit(1)
    
    # 设置信号处理以确保正常退出时释放锁
    def cleanup_handler(signum, frame):
        logger.info(f"🛑 收到信号 {signum}，正在清理...")
        lock.release()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)
    
    return lock


if __name__ == '__main__':
    # 测试
    logging.basicConfig(level=logging.INFO)
    lock = setup_single_instance_protection('/tmp/test.lock')
    print("✅ 锁已获取")
    import time
    time.sleep(5)
    lock.release()
    print("✅ 锁已释放")
