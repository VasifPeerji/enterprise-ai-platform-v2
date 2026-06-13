<script>
  let {
    title = '',
    eyebrow = '',
    accent = false,
    glow = false,
    pad = 'md',
    children,
    actions,
    class: cls = '',
  } = $props()
</script>

<section class="card {cls}" class:accent class:glow data-pad={pad}>
  {#if eyebrow || title || actions}
    <header class="card-h">
      <div>
        {#if eyebrow}<div class="eyebrow">{eyebrow}</div>{/if}
        {#if title}<h3>{title}</h3>{/if}
      </div>
      {#if actions}<div class="card-actions">{@render actions()}</div>{/if}
    </header>
  {/if}
  {@render children?.()}
</section>

<style>
  .card {
    position: relative;
    background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
    border: 1px solid var(--border-1);
    border-radius: var(--r-lg);
    box-shadow: var(--shadow-2);
  }
  .card[data-pad='md'] { padding: 22px; }
  .card[data-pad='lg'] { padding: 28px; }
  .card[data-pad='sm'] { padding: 15px; }
  .card[data-pad='none'] { padding: 0; }
  .card.accent {
    border-color: var(--accent-line);
    background:
      linear-gradient(180deg, var(--accent-soft), transparent 60%),
      linear-gradient(180deg, var(--surface-2), var(--surface-1));
  }
  .card.glow { box-shadow: var(--glow), var(--shadow-2); }
  .card-h {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
  }
  .card-h h3 { font-size: 16px; margin-top: 3px; }
  .card-actions { display: flex; gap: 8px; flex-shrink: 0; }
</style>
