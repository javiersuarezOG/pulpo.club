#!/usr/bin/env node
//
// Generate a "username:bcryptHash" line for the USERS env var on Vercel.
//
// Usage:
//     node automation/add_user.js <username> [password]
//
// If password isn't given on the command line, you'll be prompted (recommended,
// because shell history would otherwise leak it). Output is a single line you
// paste/append into the Vercel project's USERS env var.
//
// Why a separate file rather than a DB table? Phase 1 traffic is <50 paid
// accounts. Vercel env vars are diffable, free, instantly rotated, and don't
// need a migration. When this stops being painless, swap to KV or Postgres.

const bcrypt = require("bcryptjs");
const readline = require("readline");

async function promptPassword(label) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: true,
  });
  // Manually mute echo while typing the password.
  const stdin = process.stdin;
  const wasRaw = stdin.isRaw;
  return new Promise((resolve) => {
    process.stdout.write(label);
    let value = "";
    if (stdin.setRawMode) stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");
    const onData = (ch) => {
      // Handle Ctrl+C
      if (ch === "\u0003") { process.stdout.write("\n"); process.exit(130); }
      // Enter
      if (ch === "\r" || ch === "\n") {
        if (stdin.setRawMode) stdin.setRawMode(wasRaw || false);
        stdin.removeListener("data", onData);
        rl.close();
        process.stdout.write("\n");
        resolve(value);
        return;
      }
      // Backspace
      if (ch === "\u007f") { value = value.slice(0, -1); return; }
      value += ch;
    };
    stdin.on("data", onData);
  });
}

async function main() {
  const args = process.argv.slice(2);
  const username = (args[0] || "").trim().toLowerCase();
  let password = args[1];

  if (!username) {
    console.error("Usage: node automation/add_user.js <username> [password]");
    process.exit(2);
  }
  if (!/^[a-z0-9._-]{2,40}$/.test(username)) {
    console.error("Username must be 2-40 chars, lowercase letters/digits/._-");
    process.exit(2);
  }
  if (!password) {
    password = await promptPassword("password (input hidden): ");
    const confirm = await promptPassword("confirm password: ");
    if (password !== confirm) {
      console.error("Passwords didn't match.");
      process.exit(1);
    }
  }
  if (!password || password.length < 8) {
    console.error("Password must be at least 8 characters.");
    process.exit(2);
  }

  const hash = await bcrypt.hash(password, 10);
  const line = `${username}:${hash}`;

  console.log("\nAdd this line to the USERS env var on Vercel");
  console.log("(comma-separated if you already have entries):\n");
  console.log("  " + line + "\n");
  console.log("Then redeploy (or wait for the next push).");
}

main().catch((e) => { console.error(e); process.exit(1); });
