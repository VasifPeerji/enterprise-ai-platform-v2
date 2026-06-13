<script>
  import { systems, routeFor } from '../lib/registry.js'
  import { navigate } from '../lib/router.js'

  const totalDashboards = systems.reduce((n, s) => n + s.items.length, 0)
</script>

<div class="home">
  <section class="hero">
    <div class="eyebrow">Enterprise AI Platform</div>
    <h1>
      See <span class="gradient-text">inside every layer</span> of the pipeline.
    </h1>
    <p class="lede">
      An interactive dashboard for each step of the two core systems — what it does, why it's
      strong, and how it shapes the final answer. Type a query, watch the layer work, read the
      result.
    </p>
    <div class="hero-stats">
      <div class="hs"><span class="v">2</span><span class="l">core systems</span></div>
      <div class="hs"><span class="v">{totalDashboards}</span><span class="l">dashboards</span></div>
      <div class="hs"><span class="v">9</span><span class="l">routing layers</span></div>
      <div class="hs"><span class="v">9</span><span class="l">RAG steps</span></div>
    </div>
  </section>

  {#each systems as sys}
    <section class="sys {sys.theme}">
      <header class="sys-head">
        <div class="sys-mark" style="--g1:{sys.accent1}; --g2:{sys.accent2}"></div>
        <div>
          <h2>{sys.title}</h2>
          <p>{sys.tagline}</p>
        </div>
      </header>

      <div class="grid">
        {#each sys.items as item}
          <button
            class="tile"
            class:flagship={item.flagship}
            style="--g1:{sys.accent1}; --g2:{sys.accent2}"
            onclick={() => navigate(routeFor(sys.id, item.slug))}
          >
            <div class="tile-top">
              <span class="tile-badge">{item.badge}</span>
              {#if item.kind === 'overview'}
                <span class="tag overview">Overview</span>
              {:else if item.flagship}
                <span class="tag flag">Flagship</span>
              {:else if item.status === 'soon'}
                <span class="tag soon">Soon</span>
              {/if}
            </div>
            <h3>{item.title}</h3>
            <p>{item.tagline}</p>
            <span class="go">Open →</span>
          </button>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .home { display: flex; flex-direction: column; gap: 40px; animation: fade-up 0.4s ease both; }

  .hero { padding: 26px 6px 4px; }
  .hero h1 {
    font-size: 46px;
    line-height: 1.06;
    margin-top: 12px;
    max-width: 780px;
    letter-spacing: -0.03em;
  }
  .lede { margin-top: 18px; color: var(--text-2); font-size: 16.5px; max-width: 680px; }
  .hero-stats { display: flex; flex-wrap: wrap; gap: 38px; margin-top: 30px; }
  .hs { display: flex; flex-direction: column; }
  .hs .v {
    font-family: var(--font-mono);
    font-size: 30px;
    font-weight: 720;
    background: linear-gradient(95deg, var(--routing-1), var(--routing-2));
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  }
  .hs .l { font-size: 12.5px; color: var(--text-3); }

  .sys-head { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
  .sys-mark {
    width: 42px; height: 42px; border-radius: 12px;
    background: linear-gradient(135deg, var(--g1), var(--g2));
    box-shadow: 0 8px 24px -6px var(--g1);
  }
  .sys-head h2 { font-size: 22px; }
  .sys-head p { color: var(--text-2); font-size: 14px; margin-top: 3px; max-width: 720px; }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
    gap: 14px;
  }
  .tile {
    position: relative;
    text-align: left;
    background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    padding: 18px;
    overflow: hidden;
    transition: transform 0.14s ease, border-color 0.14s ease, box-shadow 0.14s ease;
  }
  .tile::before {
    content: '';
    position: absolute; left: 0; top: 0; bottom: 0;
    width: 3px;
    background: linear-gradient(180deg, var(--g1), var(--g2));
    opacity: 0.7;
  }
  .tile:hover {
    transform: translateY(-3px);
    border-color: color-mix(in srgb, var(--g1) 50%, transparent);
    box-shadow: 0 16px 40px -16px var(--g1);
  }
  .tile.flagship { border-color: color-mix(in srgb, var(--g1) 40%, transparent); }
  .tile-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .tile-badge {
    min-width: 34px; height: 26px; padding: 0 7px;
    display: grid; place-items: center;
    border-radius: 7px;
    font-family: var(--font-mono); font-size: 13px; font-weight: 700;
    color: var(--text-on-accent);
    background: linear-gradient(135deg, var(--g1), var(--g2));
  }
  .tile h3 { font-size: 16px; }
  .tile p { color: var(--text-2); font-size: 13px; margin-top: 6px; min-height: 34px; }
  .go { display: inline-block; margin-top: 12px; font-size: 13px; font-weight: 650; color: var(--g1); }
  .tag {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 3px 8px; border-radius: 6px;
  }
  .tag.overview { color: var(--text-2); background: var(--surface-3); }
  .tag.flag { color: var(--g1); background: color-mix(in srgb, var(--g1) 16%, transparent); }
  .tag.soon { color: var(--text-3); background: var(--surface-3); }

  @media (max-width: 720px) {
    .hero h1 { font-size: 32px; }
  }
</style>
