/* Veda Dashboard JS.
   Six small things, no framework, no dependencies:
     1. Theme picker (persists choice in localStorage).
     2. Top-nav active state from URL.
     3. Sortable table headers (click to sort by column).
     4. Refresh-price button (calls /api/quote and shows JSON inline).
     5. Position page: sub-nav scrollspy + expand/collapse-all + hide-empty.
     6. Smooth scroll offset for anchor clicks (CSS handles the smoothness).
*/

(function () {
  'use strict';

  // ---- 1. Theme picker -----------------------------------------------------
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('veda.theme', theme); } catch (e) { /* ignore */ }
    document.querySelectorAll('.theme-picker button').forEach(function (btn) {
      btn.setAttribute(
        'aria-pressed',
        btn.dataset.themeSet === theme ? 'true' : 'false'
      );
    });
    var marker = document.getElementById('current-theme');
    if (marker) marker.textContent = theme;
  }

  function initTheme() {
    var current = (function () {
      try { return localStorage.getItem('veda.theme') || 'system'; }
      catch (e) { return 'system'; }
    })();
    applyTheme(current);
    document.querySelectorAll('.theme-picker button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        applyTheme(btn.dataset.themeSet);
      });
    });
  }

  // ---- 2. Top-nav active state --------------------------------------------
  function initTopNavActive() {
    var path = window.location.pathname;
    document.querySelectorAll('.topbar .nav a[data-nav]').forEach(function (a) {
      var key = a.dataset.nav;
      var matches = (
        (key === 'overview' && path === '/') ||
        (key === 'journal' && path.startsWith('/journal')) ||
        (key === 'settings' && path.startsWith('/settings'))
      );
      if (matches) a.classList.add('active');
    });
  }

  // ---- 3. Sortable tables --------------------------------------------------
  function parseCell(cell) {
    var raw = (cell.textContent || '').trim();
    if (!raw || raw === '\u2014' || raw === '-') return null;
    // Strip currency / pct / commas / whitespace before float parse.
    var num = parseFloat(raw.replace(/[\u20b9$,\s]/g, '').replace(/%$/, ''));
    if (!isNaN(num) && raw.match(/[0-9]/)) return num;
    return raw.toLowerCase();
  }

  function compare(a, b, dir) {
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    if (typeof a === 'number' && typeof b === 'number') {
      return dir === 'asc' ? a - b : b - a;
    }
    var s = String(a).localeCompare(String(b));
    return dir === 'asc' ? s : -s;
  }

  function initSortableTables() {
    document.querySelectorAll('table.sortable').forEach(function (table) {
      var ths = table.querySelectorAll('thead th');
      ths.forEach(function (th, idx) {
        th.addEventListener('click', function () {
          var dir = th.dataset.sort === 'asc' ? 'desc' : 'asc';
          ths.forEach(function (h) { h.removeAttribute('data-sort'); });
          th.dataset.sort = dir;
          var tbody = table.tBodies[0];
          var rows = Array.from(tbody.querySelectorAll('tr'));
          rows.sort(function (r1, r2) {
            var a = parseCell(r1.cells[idx]);
            var b = parseCell(r2.cells[idx]);
            return compare(a, b, dir);
          });
          rows.forEach(function (r) { tbody.appendChild(r); });
        });
      });
    });
  }

  // ---- 4. Refresh-price button --------------------------------------------
  function placeResultUnder(button, html, isError) {
    var dedicated = document.querySelector(
      '.quote-result[data-ticker="' + button.dataset.ticker + '"]'
    );
    if (dedicated) {
      dedicated.innerHTML = html;
      dedicated.classList.toggle('quote-error', !!isError);
      dedicated.classList.toggle('quote-ok', !isError);
      return;
    }
    var span = button.nextElementSibling;
    if (!span || !span.classList.contains('inline-quote')) {
      span = document.createElement('span');
      span.className = 'inline-quote meta';
      button.parentNode.insertBefore(span, button.nextSibling);
    }
    span.innerHTML = html;
    span.style.color = isError ? 'var(--red)' : 'var(--green)';
  }

  function initRefreshButtons() {
    document.querySelectorAll('button.refresh-quote').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var ticker = btn.dataset.ticker;
        if (!ticker) return;
        btn.disabled = true;
        var orig = btn.textContent;
        btn.textContent = 'fetching...';
        placeResultUnder(btn, '', false);
        fetch('/api/quote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: ticker })
        }).then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        }).then(function (r) {
          if (r.ok && r.data && r.data.last_close) {
            placeResultUnder(
              btn,
              ' \u2192 ' + r.data.last_close +
                (r.data.currency ? ' ' + r.data.currency : '') +
                ' (as_of ' + (r.data.as_of || '?') + ', ' +
                (r.data.source || 'fetch_quote.py') + ')',
              false
            );
          } else {
            placeResultUnder(
              btn,
              ' error: ' + (r.data && (r.data.error || r.data.message) || 'fetch failed'),
              true
            );
          }
        }).catch(function (err) {
          placeResultUnder(btn, ' error: ' + err.message, true);
        }).finally(function () {
          btn.disabled = false;
          btn.textContent = orig;
        });
      });
    });
  }

  // ---- 5. Position-page sub-nav -------------------------------------------
  function initSubnav() {
    var subnav = document.querySelector('.subnav');
    if (!subnav) return;

    var sections = Array.from(document.querySelectorAll('.section-anchor'));
    var links = Array.from(subnav.querySelectorAll('a[href^="#"]'));

    // Active-state scrollspy (whichever section's top is closest to the
    // top of the viewport, accounting for sticky header offset).
    function updateActive() {
      var topbar = document.querySelector('.topbar');
      var headerOffset = (topbar ? topbar.offsetHeight : 0) + 24;
      if (!subnav.classList.contains('position-sidebar')) {
        headerOffset += subnav.offsetHeight;
      }
      var bestId = null;
      var bestDist = Infinity;
      for (var i = 0; i < sections.length; i++) {
        var rect = sections[i].getBoundingClientRect();
        if (rect.top <= headerOffset + 5) {
          var dist = headerOffset - rect.top;
          if (dist < bestDist) {
            bestDist = dist;
            bestId = sections[i].id;
          }
        }
      }
      if (!bestId && sections.length > 0) bestId = sections[0].id;
      links.forEach(function (a) {
        a.classList.toggle('active', a.getAttribute('href') === '#' + bestId);
      });
    }
    var ticking = false;
    window.addEventListener('scroll', function () {
      if (!ticking) {
        requestAnimationFrame(function () { updateActive(); ticking = false; });
        ticking = true;
      }
    });
    updateActive();

    // Expand all / collapse all / hide empty
    var expandBtn   = document.getElementById('expand-all');
    var collapseBtn = document.getElementById('collapse-all');
    var hideBtn     = document.getElementById('hide-empty');

    if (expandBtn) {
      expandBtn.addEventListener('click', function () {
        document.querySelectorAll('details.md-detail').forEach(function (d) {
          d.open = true;
        });
      });
    }
    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () {
        document.querySelectorAll('details.md-detail').forEach(function (d) {
          d.open = false;
        });
      });
    }
    if (hideBtn) {
      var hidden = false;
      hideBtn.addEventListener('click', function () {
        hidden = !hidden;
        hideBtn.setAttribute('aria-pressed', hidden ? 'true' : 'false');
        hideBtn.textContent = hidden ? 'show empty' : 'hide empty';
        document.querySelectorAll('section.section-group[data-empty="true"]').forEach(function (sec) {
          sec.style.display = hidden ? 'none' : '';
        });
        document.querySelectorAll('.subnav a.empty-section').forEach(function (a) {
          a.style.display = hidden ? 'none' : '';
        });
      });
    }
  }

  // ---- boot ---------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initTopNavActive();
    initSortableTables();
    initRefreshButtons();
    initSubnav();
  });
})();
