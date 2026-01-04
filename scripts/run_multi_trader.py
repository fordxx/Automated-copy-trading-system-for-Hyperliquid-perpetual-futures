#!/usr/bin/env python3
"""Multi-Instance Copy Trader Runner.

启动和管理多个跟单实例，每个实例使用不同的钱包跟踪不同的leader。
支持多进程模式，确保隔离性和稳定性。

单进程保护：
- 该程序同时只能运行一个主进程
- 尝试启动多个会立即失败
- 自动清理已死亡进程的锁文件
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
from dotenv import load_dotenv, dotenv_values

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.copy_trader import HyperliquidCopyTrader
from src.utils.helpers import setup_logging
from src.utils.single_instance_lock import SingleInstanceLock


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
    
    @staticmethod
    def _run_instance(global_config: dict, instance_config: dict, instance_name: str):
        """在子进程中运行单个实例"""
        try:
            # 设置进程标题
            import setproctitle
            setproctitle.setproctitle(f"copybot-{instance_name}")
        except ImportError:
            pass

        # Load repo-root .env so per-instance secrets can be provided via environment variables
        # instead of storing private keys in YAML.
        # Best-effort: make .env values available to this subprocess.
        # We still read directly from dotenv_values() in _set_env_vars for robustness.
        try:
            load_dotenv(dotenv_path=project_root / ".env", override=False)
        except Exception:
            pass

        try:
            # 创建日志目录
            log_dir = Path(global_config['logging']['base_dir'])
            log_dir.mkdir(parents=True, exist_ok=True)

            # 配置日志
            log_file = log_dir / f"{instance_name}.log"
            log_config = {
                'logging': {
                    'level': global_config['logging']['level'],
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
            merged_config = MultiInstanceManager._merge_config_static(global_config, instance_config)

            # 创建临时配置文件（使用环境变量传递敏感信息）
            MultiInstanceManager._set_env_vars_static(global_config, instance_config, instance_name)

            # 创建trader实例
            trader = HyperliquidCopyTrader(config_dict=merged_config)

            # 运行trader
            asyncio.run(trader.start())

        except Exception as e:
            logging.error(f"❌ Instance {instance_name} error: {e}")
            logging.exception("Instance error details")
            sys.exit(1)
    
    @staticmethod
    def _merge_config_static(global_config: dict, instance_config: dict) -> dict:
        """合并全局配置和实例配置（静态版本）"""
        telegram_cfg = dict(global_config.get('telegram', {}) or {})
        telegram_cfg.update(instance_config.get('telegram', {}) or {})
        merged = {
            'target_address': instance_config['target_address'],
            'exclude_addresses': instance_config.get('exclude_addresses', []),
            'copy_trading': instance_config['copy_trading'],
            'risk_management': instance_config.get('risk_management', {}),
            'hyperliquid': instance_config['hyperliquid'],
            'monitoring': instance_config.get('monitoring', {}),
            'logging': global_config['logging'],
            'telegram': telegram_cfg,
        }

        # 添加use_testnet
        merged['hyperliquid']['use_testnet'] = global_config.get('use_testnet', False)

        return merged

    def _merge_config(self, instance_config: dict) -> dict:
        """合并全局配置和实例配置"""
        return self._merge_config_static(self.config['global_settings'], instance_config)

    @staticmethod
    def _instance_env_suffix(instance_name: str) -> str:
        """Normalize instance name for environment variable suffixes."""
        import re

        raw = str(instance_name or "").strip().upper()
        # Replace non-alnum with underscores (e.g. trader-1 -> TRADER_1)
        raw = re.sub(r"[^A-Z0-9]+", "_", raw)
        raw = raw.strip("_")
        return raw or "INSTANCE"
    
    @staticmethod
    def _set_env_vars_static(global_config: dict, instance_config: dict, instance_name: str):
        """为实例设置环境变量（静态版本）"""
        # 设置实例特定的环境变量
        suffix = MultiInstanceManager._instance_env_suffix(instance_name)
        os.environ[f'INSTANCE_NAME'] = instance_name
        os.environ['TARGET_ADDRESS'] = str(instance_config['target_address'])
        os.environ['HYPERLIQUID_ACCOUNT_ADDRESS'] = str(instance_config['hyperliquid']['account_address'])

        # Prefer per-instance private key from env:
        #   HYPERLIQUID_PRIVATE_KEY_<INSTANCE_NAME>
        # This avoids storing secrets in YAML configs.
        env_key = f"HYPERLIQUID_PRIVATE_KEY_{suffix}"
        private_key = os.getenv(env_key)
        if not private_key:
            try:
                dotenv_kv = dotenv_values(project_root / ".env")
                private_key = str(dotenv_kv.get(env_key) or "")
            except Exception:
                private_key = ""
        if not private_key:
            # Backward-compatible fallback: single-instance key.
            private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY") or ""
        if not private_key:
            private_key = instance_config['hyperliquid'].get('private_key', '')

        # Fail fast with a helpful error if the key isn't usable.
        if not isinstance(private_key, str) or not private_key.startswith("0x") or len(private_key) != 66:
            raise ValueError(
                f"Missing/invalid private key for instance '{instance_name}'. "
                f"Set {env_key} in .env (recommended) or provide hyperliquid.private_key in the instance config."
            )
        os.environ['HYPERLIQUID_PRIVATE_KEY'] = private_key

        # Ensure instance config is not accidentally overridden by global .env values:
        # CopyTrader always applies env-overrides, so we inject per-instance env vars here.
        copy_cfg = instance_config.get("copy_trading", {}) or {}
        os.environ["COPY_MODE"] = str(copy_cfg.get("copy_mode", "position") or "position")
        os.environ["COPY_RATIO"] = str(copy_cfg.get("copy_ratio", 0.1))
        os.environ["MAX_POSITION_SIZE"] = str(copy_cfg.get("max_position_size", 1.0))
        os.environ["MIN_TRADE_SIZE"] = str(copy_cfg.get("min_trade_size", 0.01))
        os.environ["MAX_LEVERAGE"] = str(copy_cfg.get("max_leverage", 5))
        os.environ["MAX_NOTIONAL_PER_TRADE_USD"] = str(copy_cfg.get("max_notional_per_trade_usd", 0.0))

        # Per-instance risk management: allows independent stop-loss/drawdown per wallet.
        risk_cfg = instance_config.get("risk_management", {}) or {}
        if risk_cfg:
            if "max_drawdown" in risk_cfg:
                os.environ["MAX_DRAWDOWN"] = str(risk_cfg.get("max_drawdown"))
            if "stop_loss_ratio" in risk_cfg:
                os.environ["STOP_LOSS_RATIO"] = str(risk_cfg.get("stop_loss_ratio"))
            if "stop_loss_close_pct" in risk_cfg:
                os.environ["STOP_LOSS_CLOSE_PCT"] = str(risk_cfg.get("stop_loss_close_pct"))
            if "take_profit_ratio" in risk_cfg:
                os.environ["TAKE_PROFIT_RATIO"] = str(risk_cfg.get("take_profit_ratio"))

        # Exclude addresses: env expects comma-separated string.
        exclude = instance_config.get("exclude_addresses", []) or []
        if isinstance(exclude, list):
            os.environ["EXCLUDE_ADDRESSES"] = ",".join(str(a).strip() for a in exclude if str(a).strip())
        else:
            os.environ["EXCLUDE_ADDRESSES"] = str(exclude)

        # Telegram per-instance overrides (support separate chat IDs per wallet).
        telegram_cfg = dict(global_config.get("telegram", {}) or {})
        telegram_cfg.update(instance_config.get("telegram", {}) or {})
        env_bot = os.getenv(f"TELEGRAM_BOT_TOKEN_{suffix}") or ""
        env_chat = os.getenv(f"TELEGRAM_CHAT_ID_{suffix}") or ""
        if env_bot:
            telegram_cfg["bot_token"] = env_bot
        if env_chat:
            telegram_cfg["chat_id"] = env_chat
        if "enabled" in telegram_cfg:
            os.environ["TELEGRAM_ENABLED"] = "true" if telegram_cfg.get("enabled") else "false"
        if telegram_cfg.get("bot_token"):
            os.environ["TELEGRAM_BOT_TOKEN"] = str(telegram_cfg.get("bot_token"))
        if telegram_cfg.get("chat_id"):
            os.environ["TELEGRAM_CHAT_ID"] = str(telegram_cfg.get("chat_id"))

        # Network selection: enforce per-instance consistent setting.
        os.environ["HYPERLIQUID_ENV"] = "testnet" if bool(global_config.get("use_testnet")) else "mainnet"

        if instance_config['hyperliquid'].get('vault_address'):
            os.environ['HYPERLIQUID_VAULT_ADDRESS'] = instance_config['hyperliquid']['vault_address']

    def _set_env_vars(self, instance_config: dict, instance_name: str):
        """为实例设置环境变量"""
        return self._set_env_vars_static(self.config['global_settings'], instance_config, instance_name)
    
    def start_instance(self, instance_name: str, instance_config: dict):
        """启动单个实例"""
        if instance_name in self.processes and self.processes[instance_name].is_alive():
            print(f"⚠️  Instance '{instance_name}' is already running")
            return

        print(f"🚀 Starting instance: {instance_name}")
        print(f"   Target: {instance_config['target_address'][:10]}...")
        print(f"   Account: {instance_config['hyperliquid']['account_address'][:10]}...")
        print(f"   Copy Ratio: {instance_config['copy_trading']['copy_ratio'] * 100:.1f}%")

        # 创建进程 - 传递 global_config 作为参数，避免 pickle self
        process = mp.Process(
            target=MultiInstanceManager._run_instance,
            args=(self.config['global_settings'], instance_config, instance_name),
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
    # 🔒 单进程保护：获取互斥锁
    lock_file = project_root / 'logs' / 'multi_trader.lock'
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = SingleInstanceLock(str(lock_file))
    
    # 只在启动真实实例时检查锁（status和monitor除外初期检查）
    # monitor 会在启动实例时检查
    parser_peek = argparse.ArgumentParser(add_help=False)
    parser_peek.add_argument('action', nargs='?', default='status')
    args_peek, _ = parser_peek.parse_known_args()
    
    # 对于 start/restart/monitor 操作，需要获取锁
    if args_peek.action in ['start', 'restart', 'monitor']:
        if not lock.acquire():
            print("\n❌ 无法启动新进程：已有其他多钱包跟单进程在运行")
            print("   请先停止现有进程：./scripts/manage_multi_trader.sh stop")
            sys.exit(1)
        
        # 注册清理函数以确保锁被释放
        import atexit
        atexit.register(lock.release)
    
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
