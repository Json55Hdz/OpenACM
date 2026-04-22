#!/usr/bin/env node
'use strict';

const { execSync, spawnSync } = require('child_process');
const path = require('path');
const os   = require('os');
const fs   = require('fs');

const IS_WIN     = process.platform === 'win32';
const REPO_URL   = 'https://github.com/Json55Hdz/OpenACM.git';
const INSTALL_DIR = process.env.OPENACM_DIR || path.join(os.homedir(), 'OpenACM');

const cmd = process.argv[2] || 'help';

// ── Helpers ──────────────────────────────────────────────────────────────────

function isInstalled() {
  return fs.existsSync(path.join(INSTALL_DIR, IS_WIN ? 'run.bat' : 'run.sh'));
}

function commandExists(name) {
  try {
    execSync(IS_WIN ? `where ${name}` : `which ${name}`, { stdio: 'ignore' });
    return true;
  } catch { return false; }
}

function sh(script, opts = {}) {
  return spawnSync(script, {
    shell: true,
    stdio: 'inherit',
    cwd: INSTALL_DIR,
    ...opts,
  });
}

function ensureInstalled() {
  if (!isInstalled()) {
    console.error(`\n  [!] OpenACM is not installed at ${INSTALL_DIR}`);
    console.error('      Run: openacm install\n');
    process.exit(1);
  }
}

// ── Commands ─────────────────────────────────────────────────────────────────

const commands = {

  install() {
    if (isInstalled()) {
      console.log(`\n  [i] OpenACM is already installed at ${INSTALL_DIR}`);
      const readline = require('readline');
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      rl.question('      Run update instead? (Y/n): ', (ans) => {
        rl.close();
        if (ans === '' || /^[yY]/.test(ans)) commands.update();
      });
      return;
    }
    if (!commandExists('git')) {
      console.error('\n  [ERROR] git is required. Install from https://git-scm.com\n');
      process.exit(1);
    }
    console.log(`\n  [*] Cloning OpenACM into ${INSTALL_DIR}...\n`);
    spawnSync(`git clone "${REPO_URL}" "${INSTALL_DIR}"`, {
      shell: true,
      stdio: 'inherit',
      cwd: os.homedir(),
    });
    if (!IS_WIN) {
      sh('chmod +x setup.sh run.sh update.sh acm.sh 2>/dev/null || true');
    }
    sh(IS_WIN ? 'setup.bat' : './setup.sh');
  },

  start() {
    ensureInstalled();
    sh(IS_WIN ? 'run.bat' : './run.sh');
  },

  stop() {
    ensureInstalled();
    sh(IS_WIN ? 'acm stop' : './acm.sh stop');
  },

  status() {
    ensureInstalled();
    sh(IS_WIN ? 'acm status' : './acm.sh status');
  },

  update() {
    ensureInstalled();
    sh(IS_WIN ? 'update.bat' : './update.sh');
  },

  repair() {
    ensureInstalled();
    sh(IS_WIN ? 'acm repair' : './acm.sh repair');
  },

  uninstall() {
    if (!isInstalled()) {
      console.log('\n  [!] OpenACM is not installed, nothing to remove.\n');
      return;
    }
    const readline = require('readline');
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(`\n  [!] This will delete ${INSTALL_DIR}. Are you sure? (y/N): `, (ans) => {
      rl.close();
      if (ans.toLowerCase() === 'y') {
        fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
        console.log('  [OK] OpenACM removed.\n');
      } else {
        console.log('  [--] Cancelled.\n');
      }
    });
  },

  help() {
    console.log(`
  OpenACM CLI  v${require('../package.json').version}

  Usage:  openacm <command>
          npx open-acm <command>

  Commands:
    install     Clone and set up OpenACM (first time)
    start       Start OpenACM
    stop        Stop a running instance
    status      Check if OpenACM is running
    update      Pull latest + sync deps + rebuild frontend
    repair      Reinstall Python dependencies (no git pull)
    uninstall   Remove the OpenACM installation directory

  Install dir:  ${INSTALL_DIR}
  Override:     OPENACM_DIR=/custom/path openacm install
`);
  },
};

const fn = commands[cmd];
if (!fn) {
  console.error(`\n  [!] Unknown command: "${cmd}"`);
  commands.help();
  process.exit(1);
}
fn();
