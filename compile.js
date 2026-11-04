// ValtoDEX forditasa.  Futtatas (a projektmappabol):  npm install && node compile.js
// Kimenet: build/ValtoDEX.json (abi + bytecode + metadata), amit a telepit.py hasznal.
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const SOLC_VERSION = "0.8.28";
if (!solc.version().startsWith(SOLC_VERSION)) {
  console.error(`solc ${SOLC_VERSION} kell (npm install), most: ${solc.version()}`);
  process.exit(1);
}

const root = __dirname;
const source = fs.readFileSync(path.join(root, "contracts", "ValtoDEX.sol"), "utf8");
const input = {
  language: "Solidity",
  sources: { "ValtoDEX.sol": { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 1000 },
    evmVersion: "cancun",
    metadata: { bytecodeHash: "ipfs" },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "metadata"] } },
  },
};
const out = JSON.parse(solc.compile(JSON.stringify(input)));
let hiba = false;
for (const e of out.errors || []) {
  if (e.severity === "error") { console.error(e.formattedMessage); hiba = true; }
  else console.warn(e.formattedMessage);
}
if (hiba) process.exit(1);

// --- teszt-segedszerzodesek (csak a pytest-hez, nem telepitjuk) ---
const mocksPath = path.join(root, "tests", "contracts", "Mocks.sol");
if (fs.existsSync(mocksPath)) {
  const mi = { ...input, sources: { "Mocks.sol": { content: fs.readFileSync(mocksPath, "utf8") } } };
  const mo = JSON.parse(solc.compile(JSON.stringify(mi)));
  for (const e of mo.errors || []) if (e.severity === "error") { console.error(e.formattedMessage); process.exit(1); }
  const mocks = {};
  for (const [name, m] of Object.entries(mo.contracts["Mocks.sol"]))
    mocks[name] = { abi: m.abi, bytecode: "0x" + m.evm.bytecode.object };
  fs.mkdirSync(path.join(root, "build"), { recursive: true });
  fs.writeFileSync(path.join(root, "build", "TestMocks.json"), JSON.stringify(mocks, null, 2));
}

const c = out.contracts["ValtoDEX.sol"]["ValtoDEX"];
fs.mkdirSync(path.join(root, "build"), { recursive: true });
fs.writeFileSync(path.join(root, "build", "ValtoDEX.json"), JSON.stringify({
  contractName: "ValtoDEX",
  compiler: solc.version(),
  settings: input.settings,
  abi: c.abi,
  bytecode: "0x" + c.evm.bytecode.object,
  metadata: c.metadata,
}, null, 2));
console.log(`ValtoDEX: ${c.evm.bytecode.object.length / 2} bajt, ` +
  `${c.abi.filter(x => x.type === "function").length} fuggveny, solc ${solc.version()}`);
console.log("FORDITAS OK -> build/ValtoDEX.json");
