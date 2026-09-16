/* Moglin Bot frontend controller */
document.addEventListener('DOMContentLoaded', () => {
  // --- elements ---
  const navButtons = document.querySelectorAll('.nav-btn');
  const tabs = document.querySelectorAll('.tab');
  const tabTitle = document.getElementById('tab-title');
  const tabSubtitle = document.getElementById('tab-subtitle');

  const btnLaunch = document.getElementById('btn-launch');
  const btnLaunch2 = document.getElementById('btn-launch-2');
  const btnClose = document.getElementById('btn-close-game');
  const gameHero = document.getElementById('game-hero');
  const gameStatusbar = document.getElementById('game-statusbar');
  const gameRunningPill = document.getElementById('game-running-pill');
  const gamePid = document.getElementById('game-pid');
  const gameUrlHint = document.getElementById('game-url-hint');

  const ruffleDot = document.getElementById('ruffle-dot');
  const ruffleStatus = document.getElementById('ruffle-status');

  const consoleEl = document.getElementById('console');
  const logFilter = document.getElementById('log-filter');
  const btnClearLogs = document.getElementById('btn-clear-logs');

  const tabInfo = {
    game: { title: 'Game', subtitle: 'Launch and play the real AQW client via the bundled Flash emulator' },
    trainer: { title: 'Trainer & Bot', subtitle: 'Automation engine (coming in the next milestone)' },
    scripts: { title: 'Scripts', subtitle: 'Bot script manager (coming soon)' },
    logs: { title: 'Logs', subtitle: 'Client activity log' },
  };

  // --- logging ---
  function log(msg, cls = '') {
    const line = document.createElement('div');
    line.className = 'log-line' + (cls ? ' ' + cls : '');
    line.textContent = msg;
    consoleEl.appendChild(line);
    if (consoleEl.childNodes.length > 400) consoleEl.removeChild(consoleEl.firstChild);
    applyFilter(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
  window.addLog = log;

  function applyFilter(line) {
    const f = logFilter.value.toLowerCase();
    if (f && !line.textContent.toLowerCase().includes(f)) line.style.display = 'none';
  }
  logFilter.addEventListener('input', () => {
    consoleEl.querySelectorAll('.log-line').forEach(l => {
      l.style.display = (!logFilter.value || l.textContent.toLowerCase().includes(logFilter.value.toLowerCase())) ? 'block' : 'none';
    });
  });
  btnClearLogs.addEventListener('click', () => { consoleEl.innerHTML = ''; });

  // --- navigation ---
  navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      navButtons.forEach(b => b.classList.remove('active'));
      tabs.forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.getAttribute('data-tab');
      document.getElementById('tab-' + target).classList.add('active');
      tabTitle.textContent = tabInfo[target].title;
      tabSubtitle.textContent = tabInfo[target].subtitle;
    });
  });

  // --- python api helpers ---
  function pyApi() {
    return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
  }

  function updateRuffleStatus() {
    const api = pyApi();
    if (!api) return;
    api.game_status().then(s => {
      if (s.ruffle && s.ruffle.startsWith('Ruffle ready')) {
        ruffleDot.className = 'dot ok';
        ruffleStatus.textContent = 'Ruffle ready';
      } else {
        ruffleDot.className = 'dot bad';
        ruffleStatus.textContent = 'Ruffle missing';
      }
      updateGameUI(s);
    }).catch(() => {});
  }

  function updateGameUI(s) {
    if (s && s.running) {
      gameHero.classList.add('hidden');
      gameStatusbar.classList.remove('hidden');
      gameRunningPill.textContent = '● Game running';
      gamePid.textContent = 'Process ID: ' + s.pid;
      btnLaunch.classList.add('hidden');
      btnClose.classList.remove('hidden');
    } else {
      gameHero.classList.remove('hidden');
      gameStatusbar.classList.add('hidden');
      btnLaunch.classList.remove('hidden');
      btnClose.classList.add('hidden');
    }
  }

  function launchGame() {
    const api = pyApi();
    if (!api) { log('Python bridge not ready.', 'error'); return; }
    btnLaunch.disabled = true;
    if (btnLaunch2) btnLaunch2.disabled = true;
    log('Launching AQW via Ruffle...');
    api.launch_game().then(res => {
      if (res.success) {
        log('Game launched (PID ' + res.pid + ').', 'success');
        updateRuffleStatus();
      } else {
        log('Launch failed: ' + res.error, 'error');
      }
      btnLaunch.disabled = false;
      if (btnLaunch2) btnLaunch2.disabled = false;
    }).catch(err => {
      log('Launch failed: ' + err, 'error');
      btnLaunch.disabled = false;
      if (btnLaunch2) btnLaunch2.disabled = false;
    });
  }

  btnLaunch.addEventListener('click', launchGame);
  if (btnLaunch2) btnLaunch2.addEventListener('click', launchGame);

  btnClose.addEventListener('click', () => {
    const api = pyApi();
    if (!api) return;
    api.close_game().then(() => {
      log('Game closed.', 'success');
      updateRuffleStatus();
    });
  });

  // --- init: wait for pywebview to inject its API asynchronously ---
  function waitForApi(attempts) {
    const api = pyApi();
    if (api) {
      initApp(api);
      return;
    }
    if (attempts > 0) {
      setTimeout(() => waitForApi(attempts - 1), 100);
    } else {
      log('Python bridge not available (running outside the desktop app?).', 'error');
    }
  }

  function initApp(api) {
    api.app_info().then(info => {
      // Apply branding from Python (single source of truth).
      if (info && info.website_url) {
        document.title = info.name + ' by ' + info.website;
        document.querySelectorAll('.sidebar-credit a, .app-footer a').forEach(a => {
          a.href = info.website_url;
          a.textContent = info.website;
        });
      }
      log(info.name + ' — official site: ' + info.website, 'success');
    }).catch(() => {});

    api.load_settings().then(s => {
      gameUrlHint.textContent = s.game_url || '';
    }).catch(() => {});

    updateRuffleStatus();
    // Poll so the Close Game -> Launch Game state stays correct even when the
    // user closes the game window directly.
    setInterval(updateRuffleStatus, 1500);
  }

  waitForApi(100);
});
