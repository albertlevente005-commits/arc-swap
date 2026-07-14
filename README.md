# ARC Swap — a minimal AMM DEX on Arc Testnet

A small but complete **automated market maker** (Uniswap-style, x·y=k, 0.3% fee) running on
**Arc Testnet** (Circle's stablecoin-native L1), with a clean web UI you can drive either from
a server-side **Circle wallet** or from your own **MetaMask**.

Built for the Arc **Programmable Money** hackathon (2026).

## Live on Arc Testnet

- **ValtoDEX contract:** [`0xefa6efae5962fb59b90968f80b50841efdd0a806`](https://testnet.arcscan.app/address/0xefa6efae5962fb59b90968f80b50841efdd0a806)
- **Pools:** `USDC/EURC` and `USDC/cirBTC` (seeded with live liquidity)
- Chain id `5042002` · gas is paid in USDC (Arc-native)

## What it does

- **`createPool` / `addLiquidity` / `removeLiquidity`** — constant-product pools with LP shares
- **`getQuote` / `swap`** — price quote and swap with a 0.3% fee kept in the pool (earned by LPs)
- Web UI with live quotes, price-impact display, pool reserves, balances and on-chain swap history
- **Two ways to trade:**
  - **Circle mode** — the server signs with a Circle Developer-Controlled Wallet (no private keys in the browser)
  - **MetaMask mode** — you sign in your own wallet; the app adds/switches to Arc Testnet automatically
- Optional **swap agent** (`valto_ugynok.py`) that fulfils `[skill:valtas]` jobs on the companion
  [arc-platform](https://github.com/albertlevente005-commits/arc-platform) marketplace

## Files

| File | Purpose |
|---|---|
| `contracts/ValtoDEX.sol` | The AMM contract (pools, liquidity, swap) |
| `build/ValtoDEX.json` | Compiled ABI + bytecode (ready to deploy) |
| `compile.js` | Compile the contract with solc |
| `telepit.py` | Deploy the DEX to Arc (Circle Smart Contract Platform) |
| `pool_feltoltes.py` | Create the pools and seed initial liquidity |
| `valto_app.py` | Web swap UI — http://127.0.0.1:8060 |
| `valto_ugynok.py` | Optional marketplace swap agent |
| `valto_config.py` | Tokens, pools, addresses, ABIs |
| `config.py`, `mag/`, `ugynok.py` | Shared core (Circle client, chain reader, helpers) |

## Quickstart

Prerequisites: Python 3.10+, a [Circle Console](https://console.circle.com) API key (TEST env)
with a registered entity secret, and some testnet USDC + EURC
([faucet](https://faucet.circle.com), network: Arc Testnet).

```bash
pip install -r requirements.txt
copy .env.minta .env          # then fill in your Circle credentials
```

Set your own wallet address in `config.py` (`MEGRENDELO_CIM`, `TELEPITO_CIM`), then:

```bash
node compile.js               # -> build/ValtoDEX.json  (already included)
python telepit.py             # deploy the DEX (saves valto_cimek.json)
python pool_feltoltes.py      # create pools + seed liquidity
python valto_app.py           # open http://127.0.0.1:8060
```

> The web UI is served on port **8060** (Chrome blocks 5060 as an unsafe port).

## How the AMM prices a swap

Each pool keeps the product of its two reserves constant (x·y=k). The bigger your trade relative
to the pool, the worse the rate (price impact). The 0.3% fee stays in the pool, so it accrues to
liquidity providers.

## Notes

- Testnet demo — the contract is **not audited**, do not use with real funds.
- Code comments and the `OLVASS_EL.md` guide are in Hungarian (the author's language); the UI is English.
- Runtime state lives in `adat/` (auto-created, git-ignored).

## License

MIT
