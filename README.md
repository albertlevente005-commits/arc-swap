# ARC Swap — AMM DEX on Arc (mainnet-ready)

A small but complete **automated market maker** (Uniswap-style, x·y=k, 0.3% fee) for
**Arc** (Circle's stablecoin-native L1), with a web UI you can drive from your own **MetaMask**
or (operator only) from a server-side **Circle wallet**.

Started as an Arc *Programmable Money* hackathon project on Arc Testnet; this version is
prepared for **Arc mainnet** (chain id `5042`). The Hungarian step-by-step guide is in
[`MAINNET.md`](MAINNET.md) and [`OLVASS_EL.md`](OLVASS_EL.md).

## Networks

| | Mainnet | Testnet |
|---|---|---|
| `ARC_HALOZAT` | `mainnet` (default) | `testnet` |
| Chain id | 5042 | 5042002 |
| RPC | `https://rpc.mainnet.arc.io` | `https://rpc.testnet.arc.io` |
| Explorer | https://explorer.arc.io | https://explorer.testnet.arc.io |
| Circle blockchain id | `ARC` | `ARC-TESTNET` |
| Deployed DEX | `valto_cimek.mainnet.json` (written by `telepit.py`) | `valto_cimek.testnet.json` |

Token addresses (USDC `0x3600…`, EURC, cirBTC) and ERC-8004 registries per network are in
`config.py`, taken from [docs.arc.io](https://docs.arc.io/arc/references/contract-addresses).
Gas is paid in USDC (native, 18 decimals); the contract only ever moves USDC through the
6-decimal ERC-20 interface.

## What it does

- `createPool` / `addLiquidity` / `removeLiquidity` — constant-product pools with LP shares
- `getQuote` / `swap` — quote and swap with a 0.3% fee kept in the pool (earned by LPs)
- Web UI: live quotes, price impact, adjustable slippage, pool reserves, balances, LP position,
  on-chain swap history
- **MetaMask mode** (default): you sign in your own wallet; the app adds/switches to Arc
- **Circle mode** (operator): the server signs with a Circle developer-controlled wallet, protected by
  `VALTO_ADMIN_TOKEN`
- Optional **swap agent** (`valto_ugynok.py`) fulfilling `[skill:valtas]` ERC-8183 jobs

## Production hardening (vs. the testnet demo)

**Contract (`contracts/ValtoDEX.sol`, solc 0.8.28)**
- reentrancy guard, safe ERC-20 calls (non-standard return values handled)
- accounting uses the amount actually received (fee-on-transfer safe)
- `MINIMUM_LIQUIDITY` lock on the first deposit (share-inflation attack)
- `deadline` on every state-changing call; slippage guards on add/remove/swap
- proportional `addLiquidity` (only what the pool ratio needs is pulled)
- duplicate pairs rejected; `poolIdFor` / `poolExists` lookups
- owner: `pause`/`unpause` (swaps + deposits only — **withdrawals can never be paused**),
  restricted pool creation, two-step ownership transfer
- native value (`msg.value`) rejected

**App**
- network selected by `ARC_HALOZAT`, chain-id verified against the RPC at start-up
- no hard-coded wallets; everything secret/deployment-specific comes from `.env`
- write endpoints (server wallet) require an admin token; without one only MetaMask mode exists
- input validation, no internal error leakage, security headers + CSP, `ethers` served locally
- production WSGI server (waitress), `/healthz`, rotating log file, Docker image, CI

## Files

| File | Purpose |
|---|---|
| `contracts/ValtoDEX.sol` | The AMM contract |
| `build/ValtoDEX.json` | Compiled ABI + bytecode + metadata (commit after `node compile.js`) |
| `compile.js`, `package.json` | Compile with solc 0.8.28 (`npm install && node compile.js`) |
| `telepit.py` | Deploy the DEX via Circle Smart Contract Platform (mainnet confirmation, on-chain checks) |
| `pool_feltoltes.py` | Create pools + seed liquidity (checks the initial price against a market reference) |
| `dex_admin.py` | Owner operations: pause/unpause, pool creation, ownership transfer |
| `valto_app.py` | Web swap UI + JSON API |
| `valto_ugynok.py` | Optional marketplace swap agent |
| `config.py`, `valto_config.py` | Network/tokens/pools/ABIs — single source of truth |
| `mag/`, `ugynok.py` | Shared core (Circle client, chain reader, helpers) |
| `tests/` | pytest suite on a local EVM (contract + HTTP API) |
| `MAINNET.md` | Mainnet go-live checklist (Hungarian) |

## Quickstart

```bash
pip install -r requirements.txt
npm install && node compile.js        # build/ValtoDEX.json (already included)
cp .env.minta .env                    # fill in: network, Circle LIVE keys, wallet addresses, admin token
python telepit.py                     # deploy (type MAINNET to confirm) -> valto_cimek.mainnet.json
python pool_feltoltes.py              # create pools + seed liquidity
python valto_app.py                   # http://127.0.0.1:8060
```

Tests:

```bash
pip install -r requirements-dev.txt
ARC_HALOZAT=testnet python -m pytest tests -q
```

Docker:

```bash
docker build -t arc-swap .
docker run --env-file .env -p 8060:8060 arc-swap
```

Run the app behind a TLS-terminating reverse proxy and keep Circle mode on an internal network.

## Notes

- **Not independently audited.** The test-suite covers the classic AMM pitfalls, but start with limited
  liquidity and keep the owner wallet (pause) ready.
- The first deposit into a pool sets its price — seed at the market rate or arbitrage will take the difference.
- 1000 LP shares per pool are permanently locked (`MINIMUM_LIQUIDITY`).
- The ERC-8183 marketplace used by the agent only has a Circle reference deployment on testnet; on mainnet
  point `AGENTIC_COMMERCE_CIM` / `AGENTBOND_CIM` at your own contracts.
- Code comments are in Hungarian; the UI is English.

## License

MIT (bundled `static/ethers-5.7.2.umd.min.js` is MIT, see `static/ethers-LICENSE.md`).
