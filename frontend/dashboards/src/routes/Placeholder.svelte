<script>
  import PageHeader from '../components/ui/PageHeader.svelte'
  import Card from '../components/ui/Card.svelte'
  import PrevNext from '../components/ui/PrevNext.svelte'

  let { system, item, current } = $props()
</script>

<PageHeader
  badge={item.badge}
  eyebrow={system.short}
  title={item.title}
  tagline={item.tagline}
/>

<Card eyebrow="In progress" title="This dashboard is being built">
  <p class="body">
    Every dashboard in this suite is implemented one at a time — each fully wired with a live
    input → output tester, the real configuration values, and a signature visualization — then
    verified and committed before the next begins.
  </p>
  <p class="body">
    <strong>{item.title}</strong> will cover: what the step does, why it's strong, and how it
    shapes the final output. Check back shortly, or explore the dashboards that are already live.
  </p>
  <div class="hint">
    <span class="spark"></span>
    Use the sidebar to jump to any layer or step.
  </div>
</Card>

<PrevNext {current} />

<style>
  .body { color: var(--text-2); font-size: 14.5px; margin-bottom: 12px; }
  .hint {
    display: flex; align-items: center; gap: 10px;
    margin-top: 8px; padding: 12px 14px;
    background: var(--accent-soft);
    border: 1px solid var(--accent-line);
    border-radius: var(--r-md);
    font-size: 13.5px;
    color: var(--text-1);
  }
  .spark {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent-2);
    box-shadow: 0 0 10px var(--accent-2);
  }
</style>
