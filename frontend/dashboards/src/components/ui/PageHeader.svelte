<script>
  // The hero header shared by every dashboard. `stats` is an array of
  // { value, label, tone? } shown as a quick-read metric row.
  let { badge, eyebrow = '', title, tagline = '', stats = [], children } = $props()
</script>

<header class="ph">
  <div class="ph-main">
    <div class="ph-badge">{badge}</div>
    <div class="ph-text">
      {#if eyebrow}<div class="eyebrow">{eyebrow}</div>{/if}
      <h1>{title}</h1>
      {#if tagline}<p class="tagline">{tagline}</p>{/if}
    </div>
  </div>

  {#if stats.length}
    <div class="ph-stats">
      {#each stats as s}
        <div class="ph-stat">
          <span class="v {s.tone || ''}">{s.value}</span>
          <span class="l">{s.label}</span>
        </div>
      {/each}
    </div>
  {/if}

  {#if children}<div class="ph-extra">{@render children()}</div>{/if}
</header>

<style>
  .ph {
    position: relative;
    padding: 30px 30px 26px;
    border-radius: var(--r-xl);
    border: 1px solid var(--border-1);
    background:
      radial-gradient(900px 280px at 88% -40%, var(--accent-soft), transparent 70%),
      linear-gradient(180deg, var(--surface-2), var(--surface-1));
    overflow: hidden;
    animation: fade-up 0.4s ease both;
  }
  .ph::after {
    content: '';
    position: absolute;
    left: 0; right: 0; top: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent-1), var(--accent-2), transparent);
    opacity: 0.85;
  }
  .ph-main { display: flex; gap: 20px; align-items: center; }
  .ph-badge {
    flex-shrink: 0;
    width: 64px; height: 64px;
    display: grid; place-items: center;
    border-radius: var(--r-md);
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 700;
    color: var(--text-on-accent);
    background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
    box-shadow: var(--shadow-2);
  }
  .ph-text h1 { font-size: 30px; line-height: 1.1; }
  .tagline { margin-top: 7px; color: var(--text-2); font-size: 15px; max-width: 720px; }
  .ph-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 30px;
    margin-top: 24px;
    padding-top: 22px;
    border-top: 1px solid var(--border-1);
  }
  .ph-stat { display: flex; flex-direction: column; gap: 2px; }
  .ph-stat .v {
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 700;
    color: var(--text-1);
    letter-spacing: -0.01em;
  }
  .ph-stat .v.green { color: var(--green); }
  .ph-stat .v.amber { color: var(--amber); }
  .ph-stat .v.blue { color: var(--blue); }
  .ph-stat .v.accent {
    background: linear-gradient(95deg, var(--accent-1), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  }
  .ph-stat .l { font-size: 12px; color: var(--text-3); font-weight: 550; }
  .ph-extra { margin-top: 20px; }
  @media (max-width: 720px) {
    .ph { padding: 22px; }
    .ph-text h1 { font-size: 23px; }
    .ph-stats { gap: 20px; }
  }
</style>
