/* Moglin Bot frontend controller */
document.addEventListener('DOMContentLoaded', () => {
  // --- elements ---
  const navButtons = document.querySelectorAll('.nav-btn');
  const tabs = document.querySelectorAll('.tab');
  const tabTitle = document.getElementById('tab-title');
  const tabSubtitle = document.getElementById('tab-subtitle');

  const btnLaunch = document.getElementById('btn-launch');
  const btnClose = document.getElementById('btn-close-game');

  const ruffleDot = document.getElementById('ruffle-dot');
  const ruffleStatus = document.getElementById('ruffle-status');

  // Trainer
  const usernameInput = document.getElementById('input-username');
  const passwordInput = document.getElementById('input-password');
  const serverSelect = document.getElementById('select-server');
  const roomInput = document.getElementById('input-room');
  const farmClassInput = document.getElementById('input-farm-class');
  const soloClassInput = document.getElementById('input-solo-class');
  const btnBotStart = document.getElementById('btn-bot-start');
  const btnBotStop = document.getElementById('btn-bot-stop');
  const botConnState = document.getElementById('bot-conn-state');

  // Scripts
  const selectBotModule = document.getElementById('select-bot-module');
  const btnRefreshModules = document.getElementById('btn-refresh-modules');
  const btnScriptStart = document.getElementById('btn-script-start');

  // Logs
  const consoleEl = document.getElementById('console');
  const logFilter = document.getElementById('log-filter');
  const btnClearLogs = document.getElementById('btn-clear-logs');

  const tabInfo = {
    live: { title: 'Live', subtitle: '' },
    trainer: { title: 'Trainer', subtitle: '' },
    scripts: { title: 'Scripts', subtitle: '' },
    logs: { title: 'Logs', subtitle: '' },
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

  // --- game controls (embedded Ruffle game) ---
  function launchGame() {
    // The game is embedded; (re)start it if not already loaded.
    if (!gameLoaded) {
      log('Loading game client...');
      embedGame();
      return;
    }
    log('Game is already running.');
  }
  btnLaunch.addEventListener('click', launchGame);
  btnClose.addEventListener('click', () => {
    // Closing the game just reloads the embed (the real client is in-page).
    const container = document.getElementById('game-embed');
    if (container) {
      container.innerHTML = '<div class="game-placeholder muted">Loading game client...</div>';
    }
    rufflePlayer = null;
    ruffleReady = false;
    gameLoaded = false;
    const api = pyApi();
    if (api) api.game_closed && api.game_closed();
    embedGame();
  });

  function updateRuffleStatus() {
    const api = pyApi();
    if (!api) return;
    api.game_status().then(s => {
      if (s.ruffle === 'Ready') { ruffleDot.className = 'dot ok'; ruffleStatus.textContent = 'Ready'; }
      else { ruffleDot.className = 'dot bad'; ruffleStatus.textContent = 'Not ready'; }
      if (gameLoaded) {
        btnLaunch.classList.add('hidden');
        btnClose.classList.remove('hidden');
      } else {
        btnLaunch.classList.remove('hidden');
        btnClose.classList.add('hidden');
      }
    }).catch(() => {});
  }

  // --- bot controls ---
  function compileConfig() {
    return {
      username: usernameInput.value.trim(),
      password: passwordInput.value,
      server: serverSelect.value,
      room_number: parseInt(roomInput.value) || 1,
      farm_class: farmClassInput.value.trim(),
      solo_class: soloClassInput.value.trim(),
      bot_path: selectBotModule.value || '__idle__',
      cmd_delay: 1000,
      whitelist: [],
      auto_relogin: true,
      show_chat: true,
      mute_spam: true,
      anti_mod: true,
    };
  }

  function startBot() {
    const api = pyApi();
    if (!api) return;
    const config = compileConfig();
    if (!config.username || !config.password) {
      log('Username and password are required.', 'error');
      return;
    }
    btnBotStart.disabled = true;
    log('Starting bot engine...');
    api.bot_start(config).then(res => {
      if (res.success) {
        log('Bot engine started.', 'success');
        btnBotStart.classList.add('hidden');
        btnBotStop.classList.remove('hidden');
      } else {
        log('Start failed: ' + res.error, 'error');
      }
      btnBotStart.disabled = false;
      updateBotStatus();
    });
  }

  function stopBot() {
    const api = pyApi();
    if (!api) return;
    api.bot_stop().then(res => {
      log('Bot stopped.', 'success');
      btnBotStop.classList.add('hidden');
      btnBotStart.classList.remove('hidden');
      updateBotStatus();
    });
  }

  btnBotStart.addEventListener('click', startBot);
  btnBotStop.addEventListener('click', stopBot);

  function updateBotStatus() {
    const api = pyApi();
    if (!api) return;
    api.bot_status().then(s => {
      if (s.running) {
        btnBotStart.classList.add('hidden');
        btnBotStop.classList.remove('hidden');
      } else {
        btnBotStart.classList.remove('hidden');
        btnBotStop.classList.add('hidden');
      }
      botConnState.textContent = s.connected ? '● Connected' : (s.running ? '● Connecting...' : 'Not connected');
      botConnState.className = 'status-line' + (s.connected ? ' ok' : (s.running ? ' warn' : ''));

      document.getElementById('stat-hp').textContent = s.max_hp > 0 ? `${s.hp} / ${s.max_hp}` : '-';
      document.getElementById('stat-mp').textContent = s.max_mp > 0 ? `${s.mp} / ${s.max_mp}` : '-';
      document.getElementById('stat-gold').textContent = s.gold.toLocaleString();
      document.getElementById('stat-gold-farmed').textContent = s.gold_farmed.toLocaleString();
      document.getElementById('stat-exp-farmed').textContent = s.exp_farmed.toLocaleString();
      document.getElementById('stat-state').textContent =
        s.is_dead ? 'DEAD' : (s.in_combat ? 'IN COMBAT' : (s.connected ? 'FARMING' : '-'));
      document.getElementById('stat-map').textContent = s.map || '-';
      document.getElementById('stat-cell-pad').textContent = (s.cell && s.pad) ? `${s.cell} (${s.pad})` : '-';
      document.getElementById('stat-inv').textContent = s.inventory_count;
      document.getElementById('stat-bank').textContent = s.bank_count;
      document.getElementById('stat-mons').textContent = s.monster_count;
      document.getElementById('stat-quests').textContent = s.quest_count;

      if (s.connected) {
        refreshLists();
      }
    }).catch(() => {});
  }

  function refreshLists() {
    const api = pyApi();
    if (!api) return;
    api.bot_inventory().then(items => {
      const el = document.getElementById('inventory-list');
      el.innerHTML = items.length ? items.map(i => `<div class="item-row"><span>${esc(i.name)}</span><span class="qty">${i.qty}${i.equipped ? ' ⚔' : ''}</span></div>`).join('') : '<div class="muted">Empty</div>';
    }).catch(() => {});
    api.bot_bank().then(items => {
      const el = document.getElementById('bank-list');
      el.innerHTML = items.length ? items.map(i => `<div class="item-row"><span>${esc(i.name)}</span><span class="qty">${i.qty}</span></div>`).join('') : '<div class="muted">Empty</div>';
    }).catch(() => {});
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // --- scripts ---
  function refreshModules(preferred) {
    const api = pyApi();
    if (!api) return;
    api.bot_modules().then(mods => {
      const current = preferred || selectBotModule.value || '__idle__';
      selectBotModule.innerHTML = '<option value="__idle__">Idle (stay connected)</option>' +
        mods.map(m => `<option value="${esc(m.path)}">${esc(m.name)}</option>`).join('');
      if (current) selectBotModule.value = current;
      log(`Loaded ${mods.length} bot scripts.`);
    }).catch(() => {});
  }
  btnRefreshModules.addEventListener('click', () => refreshModules());
  btnScriptStart.addEventListener('click', () => {
    const api = pyApi();
    if (!api) return;
    const config = compileConfig();
    if (!config.username || !config.password) {
      log('Enter account details in the Trainer tab first.', 'error');
      return;
    }
    log('Starting script ' + config.bot_path + '...');
    api.bot_start(config).then(res => {
      if (res.success) { log('Script started.', 'success'); updateBotStatus(); }
      else { log('Script start failed: ' + res.error, 'error'); }
    });
  });

  // --- Live game embed (Ruffle web + rbot.swf bridge) ---
  let rufflePlayer = null;   // ruffle player instance
  let ruffleReady = false;   // ruffle API is ready
  let gameLoaded = false;    // rbot.swf has loaded the real game

  function embedGame() {
    const container = document.getElementById('game-embed');
    if (!container || rufflePlayer) return;
    if (!window.RufflePlayer) { setTimeout(embedGame, 200); return; }

    try {
      const ruffle = window.RufflePlayer.newest();
      const player = ruffle.createPlayer();
      player.style.width = '100%';
      player.style.height = '100%';
      container.innerHTML = '';
      container.appendChild(player);
      const ru = player.ruffle();
      rufflePlayer = player;
      ruffleReady = !!ru;

      // Trace observer -> forward to logs.
      if (ru.traceObserver !== undefined) {
        try { ru.traceObserver = (m) => log('[game] ' + m); } catch (e) {}
      }

      // rbot.swf forwards server packets + pext to JS via ExternalInterface.call.
      // Ruffle web resolves these as indirect eval of the *name* in global scope,
      // so we must define global functions named exactly "loaded", "pext",
      // "packet", "debug", and "requestLoadGame" (matching rbot.swf's
      // Externalizer.call(...)).
      window.loaded = () => {
        gameLoaded = true;
        const api = pyApi();
        if (api) api.game_loaded();
        log('Game loaded in Ruffle.', 'success');
      };
      // rbot.swf asks JS for the game URL once its Externalizer is ready.
      // Respond by telling rbot.swf to load the default game client.
      window.requestLoadGame = () => {
        log('rbot.swf requested game load.');
        try {
          if (ru && ru.callExternalInterface) {
            ru.callExternalInterface('loadClient', null);
          }
        } catch (e) { log('loadClient error: ' + e, 'error'); }
      };
      window.pext = (packet) => {
        const api = pyApi();
        if (api) api.game_pext(String(packet));
      };
      window.packet = (packet) => {
        const api = pyApi();
        if (api) api.game_packet(String(packet));
      };
      window.debug = (message) => {
        const api = pyApi();
        if (api) api.game_debug(String(message));
        else log('[game] ' + message);
      };
      // Bridge for the bot to inject packets (called from Python via evaluate_js).
      window.__moglin_sendPacket = (packet, type) => {
        if (!ru || !ru.callExternalInterface) return false;
        try {
          ru.callExternalInterface('sendClientPacket', packet, type || 'str');
          return true;
        } catch (e) { return false; }
      };

      // Load rbot.swf (the rBot loader that loads the real game and registers
      // ExternalInterface callbacks like sendClientPacket / loadClient).
      const loadOptions = {
        url: 'rbot.swf',
        base: '.',
        allowScriptAccess: true,
        allowNetworking: 'all',
        // game.aq.com doesn't send CORS headers, so rewrite its HTTP requests
        // through our same-origin proxy (see app.py /proxy/<path>).
        urlRewriteRules: [
          [new RegExp('^https?://game\\.aq\\.com/(.*)$'), '/proxy/$1'],
        ],
      };
      ru.load(loadOptions).then(() => {
        log('rbot.swf loaded; waiting for game...');
        // The web player can auto-pause (background/hidden tab), which stalls
        // AVM2 execution so the SWF's constructor never runs and callbacks are
        // never registered. Explicitly resume/play to start frame execution.
        try { if (ru && typeof ru.resume === 'function') ru.resume(); } catch (e) {}
        try { if (player && typeof player.play === 'function') player.play(); } catch (e) {}
        // rbot.swf asks JS for the game URL via "requestLoadGame", but the
        // SWF->JS ExternalInterface direction may not fire under Ruffle. So we
        // proactively tell it to load the default game client once it's ready.
        setTimeout(() => {
          try {
            if (ru.callExternalInterface) {
              ru.callExternalInterface('loadClient', null);
              log('Sent loadClient to rbot.swf.');
            }
          } catch (e) { log('loadClient error: ' + e, 'error'); }
        }, 1500);
      }).catch((e) => {
        log('rbot.swf load error: ' + e, 'error');
      });
    } catch (e) {
      log('Game embed error: ' + e, 'error');
    }
  }

  // --- polling loops ---
  function waitForApi(attempts) {
    const api = pyApi();
    if (api) { initApp(api); return; }
    if (attempts > 0) setTimeout(() => waitForApi(attempts - 1), 100);
    else log('Python bridge not available.', 'error');
  }

  function initApp(api) {
    api.app_info().then(info => {
      if (info && info.website_url) {
        document.title = info.name + ' by ' + info.website;
        document.querySelectorAll('.app-footer a').forEach(a => { a.href = info.website_url; a.textContent = info.website; });
      }
      if (!info.engine_ready) log('aqw-python engine not found — bot features disabled.', 'error');
    }).catch(() => {});

    let savedBotPath = '__idle__';
    api.load_settings().then(s => {
      usernameInput.value = s.username || '';
      passwordInput.value = s.password || '';
      serverSelect.value = s.server || 'Artix';
      roomInput.value = s.room_number || 1;
      farmClassInput.value = s.farm_class || '';
      soloClassInput.value = s.solo_class || '';
      savedBotPath = s.bot_path || '__idle__';
    }).catch(() => {});

    refreshModules(savedBotPath);
    updateRuffleStatus();
    updateBotStatus();
    embedGame();

    // periodic status + log drain
    setInterval(() => {
      updateRuffleStatus();
      updateBotStatus();
      api.bot_logs().then(lines => lines.forEach(l => {
        if (l.trim()) log(l.trim());
      })).catch(() => {});
    }, 1500);

    // save settings on change (debounced)
    let saveTimer = null;
    function scheduleSave() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        api.save_settings(compileConfig()).catch(() => {});
      }, 800);
    }
    [usernameInput, passwordInput, serverSelect, roomInput, farmClassInput, soloClassInput, selectBotModule].forEach(el => {
      el.addEventListener('input', scheduleSave);
      el.addEventListener('change', scheduleSave);
    });
  }

  waitForApi(100);
});
