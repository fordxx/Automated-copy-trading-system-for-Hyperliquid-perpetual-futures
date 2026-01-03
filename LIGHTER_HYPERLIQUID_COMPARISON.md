# Lighter vs Hyperliquid 交易对比较

**生成时间**: 2026-01-02

## 📊 总览

| 指标 | Lighter DEX | Hyperliquid |
|------|-------------|-------------|
| 总交易对数 | **121** | **224** |
| 共同交易对 | **88** (72.7%) | **88** (39.3%) |
| 独有交易对 | **33** | **136** |

## 🎯 共同交易对 (88个)

两个平台都支持的加密货币永续合约：

```
0G, 2Z, AAVE, ADA, AERO, AI16Z, APEX, APT, ARB, ASTER,
AVAX, AVNT, BCH, BERA, BNB, BTC, CC, CRV, DOGE, DOT,
DYDX, EIGEN, ENA, ETH, ETHFI, FARTCOIN, FIL, GMX, GRASS, HBAR,
HYPE, ICP, IP, JUP, KAITO, LAUNCHCOIN, LDO, LINEA, LINK, LIT,
LTC, MEGA, MET, MKR, MNT, MON, MORPHO, NEAR, ONDO, OP,
PAXG, PENDLE, PENGU, POL, POPCAT, PROVE, PUMP, PYTH, RESOLV, S,
SEI, SKY, SOL, SPX, STABLE, STBL, STRK, SUI, SYRUP, TAO,
TIA, TON, TRUMP, TRX, UNI, VIRTUAL, VVV, WIF, WLD, WLFI,
XLM, XPL, XRP, YZY, ZEC, ZK, ZORA, ZRO
```

**热门币种覆盖**: BTC, ETH, SOL, DOGE, ARB, OP, SUI, TIA, HYPE, PENGU, TRUMP 等主流和热门币种均在两个平台都可交易。

---

## 🟦 Lighter 独有交易对 (33个)

### 💱 外汇 CFD (8个)
```
AUDUSD, EURUSD, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY, USDKRW
```

### 📈 美股 CFD (10个)
```
AAPL (苹果), AMZN (亚马逊), COIN (Coinbase), GOOGL (谷歌),
HOOD (Robinhood), META (Meta), MSFT (微软), NVDA (英伟达),
PLTR (Palantir), TSLA (特斯拉)
```

### 🪙 大宗商品/其他 (15个)
```
1000BONK, 1000FLOKI, 1000PEPE, 1000SHIB, 1000TOSHI,
CRO, DOLO, EDEN, FF, MYX, NMR, USELESS,
XAG (白银), XAU (黄金), XMR (门罗币)
```

**Lighter 特色**:
- ✅ 支持传统金融市场（外汇、美股、贵金属）
- ✅ 提供 1000x 前缀的 meme 币（类似 Hyperliquid 的 k 前缀）
- ✅ 一站式多资产交易平台

---

## 🟪 Hyperliquid 独有交易对 (136个)

### 🔤 "k" 前缀 1000x 微盘币 (7个)
```
kBONK, kDOGS, kFLOKI, kLUNC, kNEIRO, kPEPE, kSHIB
```
*(k = 1000x leverage on micro-cap meme tokens)*

### 🪙 常规加密货币 (129个)
包括但不限于：
```
ACE, AI, AIXBT, ALGO, ALT, ANIME, APE, AR, ATOM, BOME, BRETT,
CFX, COMP, ENS, ETC, FET, FTM, FTT, GALA, GOAT, INJ, MEME,
MOVE, NEIROETH, ORDI, PEPE, PNUT, RENDER, SHIA, SNX, USUAL,
ZEREBRO, ZETA, ...
```

**Hyperliquid 优势**:
- ✅ 更多山寨币/新币种选择（136 vs 33）
- ✅ 快速上新（如 MELANIA, ZEREBRO 等热点币）
- ✅ 专注于加密货币生态

---

## 💡 结论

### 🎯 共同点
- **88 个主流加密货币永续合约**都可在两个平台交易
- 覆盖 BTC, ETH, SOL 等核心资产和热门 DeFi/L1/L2/Meme 币

### 🔄 差异化
| 平台 | 核心优势 | 适合用户 |
|------|---------|---------|
| **Lighter** | 传统金融+加密货币（外汇、美股、贵金属） | 想在一个平台交易多种资产的用户 |
| **Hyperliquid** | 最全加密货币品种（224种，快速上新） | 专注加密货币、追逐热点新币的交易者 |

### 📈 跨平台套利/跟单建议
- ✅ **88个共同币种**可实现跨平台跟单/对冲
- ⚠️ Lighter 的外汇/美股仅 Lighter 独有，无法在 Hyperliquid 对冲
- ⚠️ Hyperliquid 的 136 个独有币种需要单独评估流动性

---

## 📂 数据来源

- **Lighter**: [https://mainnet.zklighter.elliot.ai](https://mainnet.zklighter.elliot.ai) (通过 lighter-sdk 获取)
- **Hyperliquid**: [https://api.hyperliquid.xyz/info](https://api.hyperliquid.xyz/info) (通过 hyperliquid-python-sdk 获取)
- **本地代码**: `/home/fordxx/perp-tools/_remote_tw168/tw168/app/lighter_client_async.py`
