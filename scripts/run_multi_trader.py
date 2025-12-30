#!/usr/bin/env python3
"""Multi-Instance Copy Trader Runner.

启动和管理多个跟单实例，每个实例使用不同的钱包跟踪不同的leader。
支持多进程模式，确保隔离性和稳定性。
"""
import asyncio
import logging
import sys
import os
import argparse
import signal
import time
from pathlib import Path
from typing import Dict, List
import multiprocessing as mp
import yaml

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.copy_trader import HyperliquidCopyTrader
from src.utils.helpers import setup_logging


class MultiInstanceManager:
    """多实例管理器"""
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.processes: Dict[str, mp.Process] = {}
        self.should_stop = False
        
        # 加载配置
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理终止信号"""
        print(f"\n🛑 Received signal {signum}, stopping all instances...")
        self.should_stop = True
        self.stop_all()
        sys.exit(0)
    
    def _run_instance(self, instance_config: dict, instance_name: str):
        """在子进程中运行单个实例"""
        try:
            # 设置进程标题
            import setproctitle
            setproctitle.setproctitle(f"copybot-{instance_name}")
        except ImportError:
            pass
        
        try:
            # 创建日志目录
            log_dir = Path(self.config['global_settings']['logging']['base_dir'])
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # 配置日志
            log_file = log_dir / f"{instance_name}.log"
            log_config = {
                'logging': {
                    'level': self.config['global_settings']['logging']['level'],
                    'file': str(log_file)
                }
            }
            setup_logging(log_config)
            
            logger = logging.getLogger(__name__)
            logger.info(f"🚀 Starting instance: {instance_name}")
            logger.info(f"📊 Target: {instance_config['target_address']}")
            logger.info(f"🏦 Account: {instance_config['hyperliquid']['account_address']}")
            logger.info(f"📈 Copy Ratio: {instance_config['copy_trading']['copy_ratio'] * 100:.1f}%")
            
            # 合并全局配置和实例配置
            merged_config = self._merge_config(instance_config)
            
            # 创建临时配置文件（使用环境变量传递敏感信息）
            self._set_env_vars(instance_config, instance_name)
            
            # 创建trader实例
            trader = HyperliquidCopyTrader(config_dict=merged_config)
            
            # 运行trader
            asyncio.run(trader.start())
            
        except Exception as e:
            logging.error(f"❌ Instance {instance_name} error: {e}")
            logging.exception("Instance error details")
            sys.exit(1)
    
    def _merge_config(self, instance_config: dict) -> dict:
        """合并全局配置和实例配置"""
        merged = {
            'target_address': instance_config['target_address'],
            'exclude_addresses': instance_config.get('exclude_addresses', []),
            'copy_trading': instance_config['copy_trading'],
            'risk_management': instance_config.get('risk_management', {}),
            'hyperliquid': instance_config['hyperliquid'],
            'monitoring': instance_config.get('monitoring', {}),
            'logging': self.config['global_settings']['logging'],
            'telegram': self.config['global_settings'].get('telegram', {})
        }
        
        # 添加use_testnet
        merged['hyperliquid']['use_testnet'] = self.config['global_settings'].get('use_testnet', False)
        
        return merged
    
    def _set_env_vars(self, instance_config: dict, instance_name: str):
        """为实例设置环境变量"""
        # 设置实例特定的环境变量
        os.environ[f'INSTANCE_NAME'] = instance_name
        os.environ['TARGET_ADDRESS'] = instance_config['target_address']
        os.environ['HYPERLIQUID_ACCOUNT_ADDRESS'] = instance_config['hyperliquid']['account_address']
        os.environ['HYPERLIQUID_PRIVATE_KEY'] = instance_config['hyperliquid']['private_key']
        
        if instance_config['hyperliquid'].get('vault_address'):
            os.environ['HYPERLIQUID_VAULT_ADDRESS'] = instance_config['hyperliquid']['vault_address']
        
        os.environ['COPY_RATIO'] = str(instance_config['copy_trading']['copy_ratio'])
        os.environ['MAX_POSITION_SIZE'] = str(instance_config['copy_trading']['max_position_size'])
        
        if self.config['global_settings'].get('use_testnet'):
            os.environ['HYPERLIQUID_ENV'] = 'testnet'
    
    def start_instance(self, instance_name: str, instance_config: dict):
        """启动单个实例"""
        if instance_name in self.processes and self.processes[instance_name].is_alive():
            print(f"⚠️  Instance '{instance_name}' is already running")
            return
        
        print(f"🚀 Starting instance: {instance_name}")
        print(f"   Target: {instance_config['target_address'][:10]}...")
        print(f"   Account: {instance_config['hyperliquid']['account_address'][:10]}...")
        print(f"   Copy Ratio: {instance_config['copy_trading']['copy_ratio'] * 100:.1f}%")
        
        # 创建进程
        process = mp.Process(
            target=self._run_instance,
            args=(instance_config, instance_name),
            name=f"copybot-{instance_name}"
        )
        process.start()
        self.processes[instance_name] = process
        
        # 等待一下确保启动
        time.sleep(1)
        
        if process.is_alive():
            print(f"✅ Instance '{instance_name}' started (PID: {process.pid})")
        else:
            print(f"❌ Instance '{instance_name}' failed to start")
    
    def stop_instance(self, instance_name: str):
        """停止单个实例"""
        if instance_name not in self.processes:
            print(f"⚠️  Instance '{instance_name}' not found")
            return
        
        process = self.processes[instance_name]
        if not process.is_alive():
            print(f"⚠️  Instance '{instance_name}' is not running")
            del self.processes[instance_name]
            return
        
        print(f"🛑 Stopping instance: {instance_name} (PID: {process.pid})")
        
        # 尝试优雅停止
        process.terminate()
        process.join(timeout=10)
        
        # 如果还在运行，强制杀死
        if process.is_alive():
            print(f"⚠️  Force killing instance: {instance_name}")
            process.kill()
            process.join()
        
        del self.processes[instance_name]
        print(f"✅ Instance '{instance_name}' stopped")
    
    def start_all(self):
        """启动所有启用的实例"""
        instances = self.config.get('trading_instances', [])
        
        if not instances:
            print("❌ No trading instances configured")
            return
        
        enabled_count = 0
        for instance in instances:
            if not instance.get('enabled', False):
                print(f"⏭️  Skipping disabled instance: {instance.get('name', 'unnamed')}")
                continue
            
            instance_name = instance.get('name')
            if not instance_name:
                print("⚠️  Skipping instance without name")
                continue
            
            self.start_instance(instance_name, instance)
            enabled_count += 1
            
            # 延迟启动，避免同时启动太多实例
            time.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"✅ Started {enabled_count} instance(s)")
        print(f"{'='*60}\n")
    
    def stop_all(self):
        """停止所有实例"""
        if not self.processes:
            print("No running instances")
            return
        
        print(f"\n{'='*60}")
        print(f"🛑 Stopping {len(self.processes)} instance(s)...")
        print(f"{'='*60}\n")
        
        for instance_name in list(self.processes.keys()):
            self.stop_instance(instance_name)
        
        print(f"\n{'='*60}")
        print(f"✅ All instances stopped")
        print(f"{'='*60}\n")
    
    def status(self):
        """显示所有实例状态"""
        instances = self.config.get('trading_instances', [])
        
        print(f"\n{'='*80}")
        print(f"{'MULTI-INSTANCE STATUS':^80}")
        print(f"{'='*80}\n")
        
        running_count = 0
        stopped_count = 0
        disabled_count = 0
        
        for instance in instances:
            instance_name = instance.get('name', 'unnamed')
            enabled = instance.get('enabled', False)
            
            if not enabled:
                print(f"⏸️  {instance_name:<20} DISABLED")
                disabled_count += 1
                continue
            
            if instance_name in self.processes and self.processes[instance_name].is_alive():
                pid = self.processes[instance_name].pid
                print(f"✅ {instance_name:<20} RUNNING (PID: {pid})")
                print(f"   Target: {instance['target_address'][:10]}...")
                print(f"   Account: {instance['hyperliquid']['account_address'][:10]}...")
                print(f"   Copy Ratio: {instance['copy_trading']['copy_ratio'] * 100:.1f}%")
                running_count += 1
            else:
                print(f"❌ {instance_name:<20} STOPPED")
                stopped_count += 1
            
            print()
        
        print(f"{'='*80}")
        print(f"Summary: {running_count} running, {stopped_count} stopped, {disabled_count} disabled")
        print(f"{'='*80}\n")
    
    def monitor(self):
        """监控模式：持续显示状态并自动重启崩溃的实例"""
        print("📊 Entering monitor mode (Press Ctrl+C to exit)...")
        print("   Auto-restart: Enabled\n")
        
        try:
            while not self.should_stop:
                # 检查每个应该运行的实例
                instances = self.config.get('trading_instances', [])
                for instance in instances:
                    if not instance.get('enabled', False):
                        continue
                    
                    instance_name = instance.get('name')
                    if not instance_name:
                        continue
                    
                    # 检查进程状态
                    if instance_name in self.processes:
                        process = self.processes[instance_name]
                        if not process.is_alive():
                            print(f"⚠️  Instance '{instance_name}' crashed, restarting...")
                            del self.processes[instance_name]
                            time.sleep(2)
                            self.start_instance(instance_name, instance)
                    else:
                        # 实例应该运行但不在进程列表中
                        print(f"⚠️  Instance '{instance_name}' not running, starting...")
                        self.start_instance(instance_name, instance)
                
                # 等待一段时间后再检查
                time.sleep(30)
                
        except KeyboardInterrupt:
            print("\n🛑 Exiting monitor mode...")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Multi-Instance Hyperliquid Copy Trader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 启动所有启用的实例
  python scripts/run_multi_trader.py start
  
  # 停止所有实例
  python scripts/run_multi_trader.py stop
  
  # 查看状态
  python scripts/run_multi_trader.py status
  
  # 监控模式（自动重启）
  python scripts/run_multi_trader.py monitor
  
  # 启动单个实例
  python scripts/run_multi_trader.py start --instance trader_1
  
  # 停止单个实例
  python scripts/run_multi_trader.py stop --instance trader_1
        """
    )
    
    parser.add_argument(
        'action',
        choices=['start', 'stop', 'restart', 'status', 'monitor'],
        help='Action to perform'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config/multi_config.yaml',
        help='Path to multi-instance config file (default: config/multi_config.yaml)'
    )
    parser.add_argument(
        '--instance',
        type=str,
        help='Specific instance name (for start/stop single instance)'
    )
    
    args = parser.parse_args()
    
    # 检查配置文件
    config_path = project_root / args.config
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        print(f"\n💡 Tip: Copy config/multi_config.yaml and customize it")
        sys.exit(1)
    
    # 创建管理器
    manager = MultiInstanceManager(str(config_path))
    
    # 执行操作
    if args.action == 'start':
        if args.instance:
            # 启动单个实例
            instances = manager.config.get('trading_instances', [])
            instance_config = next(
                (i for i in instances if i.get('name') == args.instance),
                None
            )
            if instance_config:
                if not instance_config.get('enabled', False):
                    print(f"⚠️  Instance '{args.instance}' is disabled in config")
                    sys.exit(1)
                manager.start_instance(args.instance, instance_config)
            else:
                print(f"❌ Instance '{args.instance}' not found in config")
                sys.exit(1)
        else:
            # 启动所有实例
            manager.start_all()
    
    elif args.action == 'stop':
        if args.instance:
            manager.stop_instance(args.instance)
        else:
            manager.stop_all()
    
    elif args.action == 'restart':
        if args.instance:
            manager.stop_instance(args.instance)
            time.sleep(2)
            instances = manager.config.get('trading_instances', [])
            instance_config = next(
                (i for i in instances if i.get('name') == args.instance),
                None
            )
            if instance_config:
                manager.start_instance(args.instance, instance_config)
        else:
            manager.stop_all()
            time.sleep(2)
            manager.start_all()
    
    elif args.action == 'status':
        manager.status()
    
    elif args.action == 'monitor':
        manager.start_all()
        time.sleep(2)
        manager.monitor()


if __name__ == "__main__":
    # 设置多进程启动方式
    mp.set_start_method('spawn', force=True)
    main()
