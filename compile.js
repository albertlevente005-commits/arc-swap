// ValtoDEX forditasa - a BoitBlance-nel mar telepitett solc-ot hasznalja.
// Futtatas (cmd, a projektmappabol):  node compile.js
const fs = require("fs");
const path = require("path");

let solc;
try {
  solc = require("solc"); // ha helyben van
} catch (e) {
  solc = require(path.join(__dirname, "..", "BoitBlance", "node_modules", "solc"));
}

const source = fs.readFileSync("contracts/ValtoDEX.sol", "utf8");
const input = {
  language: "Solidity",
  sources: { "ValtoDEX.sol": { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};
const out = JSON.parse(solc.compile(JSON.stringify(input)));
if (out.errors) {
  for (const e of out.errors)
    if (e.severity === "error") { console.error(e.formattedMessage); process.exit(1); }
}
fs.mkdirSync("build", { recursive: true });
const c = out.contracts["ValtoDEX.sol"]["ValtoDEX"];
fs.writeFileSync("build/ValtoDEX.json",
  JSON.stringify({ abi: c.abi, bytecode: "0x" + c.evm.bytecode.object }, null, 2));
console.log(`ValtoDEX: ${c.evm.bytecode.object.length / 2} bajt, ` +
  `${c.abi.filter(x => x.type === "function").length} fuggveny`);
console.log("FORDITAS OK -> build/ValtoDEX.json");
