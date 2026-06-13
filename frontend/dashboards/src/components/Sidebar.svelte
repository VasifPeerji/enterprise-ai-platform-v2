<script>
  import { systems, routeFor } from '../lib/registry.js'
  import { navigate } from '../lib/router.js'

  let { current } = $props()

  const isActive = (sysId, slug) => current === `/${sysId}/${slug}`
</script>

<aside class="sidebar">
  <button class="brand" onclick={() => navigate('/')} aria-label="Home">
    <span class="logo" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="30" height="30">
        <circle cx="9" cy="16" r="3.2" fill="url(#bg)" />
        <circle cx="23" cy="9" r="2.6" fill="url(#bg)" />
        <circle cx="23" cy="23" r="2.6" fill="url(#bg)" />
        <path d="M11.7 14.5 20.6 10M11.7 17.5 20.6 22" stroke="url(#bg)" stroke-width="1.7" fill="none" stroke-linecap="round" />
        <defs>
          <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#6366f1" /><stop offset="1" stop-color="#22d3ee" />
          </linearGradient>
        </defs>
      </svg>
    </span>
    <span class="brand-text">
      <span class="brand-title">Layer Dashboards</span>
      <span class="brand-sub">Enterprise AI Platform</span>
    </span>
  </button>

  <nav class="nav">
    {#each systems as sys}
      <div class="group" style="--g1:{sys.accent1}; --g2:{sys.accent2}">
        <div class="group-head">
          <i class="g-dot"></i>
          <span>{sys.short}</span>
        </div>
        <ul>
          {#each sys.items as item}
            <li>
              <button
                class="navitem"
                class:active={isActive(sys.id, item.slug)}
                onclick={() => navigate(routeFor(sys.id, item.slug))}
              >
                <span class="ni-badge" class:flagship={item.flagship}>{item.badge}</span>
                <span class="ni-label">{item.nav}</span>
                {#if item.status === 'soon'}<span class="ni-soon">soon</span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </nav>

  <div class="side-foot">
    <i class="live"></i>
    <span>Faithful client-side simulations of the real layer logic</span>
  </div>
</aside>

<style>
  .sidebar {
    width: var(--sidebar-w);
    flex-shrink: 0;
    height: 100vh;
    overflow-y: auto;
    border-right: 1px solid var(--border-1);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent);
    backdrop-filter: blur(8px);
    display: flex;
    flex-direction: column;
    padding: 16px 12px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 11px;
    background: none;
    border: none;
    padding: 8px 10px;
    margin-bottom: 8px;
    border-radius: var(--r-md);
    transition: background 0.15s ease;
  }
  .brand:hover { background: var(--surface-2); }
  .logo { display: grid; place-items: center; }
  .brand-text { display: flex; flex-direction: column; text-align: left; }
  .brand-title { font-size: 14.5px; font-weight: 700; color: var(--text-1); letter-spacing: -0.01em; }
  .brand-sub { font-size: 11px; color: var(--text-3); }

  .nav { flex: 1; display: flex; flex-direction: column; gap: 18px; margin-top: 8px; }
  .group-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.13em;
    color: var(--text-3);
  }
  .g-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: linear-gradient(135deg, var(--g1), var(--g2));
    box-shadow: 0 0 10px var(--g1);
  }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  .navitem {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    background: none;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    padding: 8px 11px;
    text-align: left;
    color: var(--text-2);
    transition: background 0.13s ease, color 0.13s ease;
  }
  .navitem:hover { background: var(--surface-2); color: var(--text-1); }
  .navitem.active {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--text-1);
  }
  .ni-badge {
    flex-shrink: 0;
    min-width: 30px;
    height: 22px;
    padding: 0 5px;
    display: grid;
    place-items: center;
    border-radius: 6px;
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 600;
    color: var(--text-2);
    background: var(--surface-3);
    border: 1px solid var(--border-1);
  }
  .navitem.active .ni-badge {
    color: var(--text-on-accent);
    background: linear-gradient(135deg, var(--g1, var(--accent-1)), var(--g2, var(--accent-2)));
    border-color: transparent;
  }
  .ni-badge.flagship { box-shadow: 0 0 0 1px var(--g1); }
  .ni-label { flex: 1; font-size: 13px; font-weight: 550; }
  .ni-soon {
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-3);
    background: var(--surface-3);
    padding: 2px 6px;
    border-radius: 5px;
  }
  .side-foot {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 12px 12px 6px;
    margin-top: 14px;
    border-top: 1px solid var(--border-1);
    font-size: 11px;
    color: var(--text-3);
    line-height: 1.4;
  }
  .live {
    flex-shrink: 0;
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse-dot 2.4s ease-in-out infinite;
  }
</style>
