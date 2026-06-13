<script>
  let { value, label = '', sub = '', tone = 'accent', mono = true } = $props()
</script>

<div class="stat">
  <div class="v {tone}" class:mono>{value}</div>
  {#if label}<div class="l">{label}</div>{/if}
  {#if sub}<div class="s">{sub}</div>{/if}
</div>

<style>
  .stat { display: flex; flex-direction: column; gap: 2px; }
  .v {
    font-size: 26px;
    font-weight: 720;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }
  .v.mono { font-family: var(--font-mono); }
  .v.accent { color: var(--text-1); }
  .v.gradient {
    background: linear-gradient(95deg, var(--accent-1), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  }
  .v.green { color: var(--green); }
  .v.amber { color: var(--amber); }
  .v.red { color: var(--red); }
  .v.blue { color: var(--blue); }
  .l { font-size: 12.5px; color: var(--text-2); font-weight: 550; }
  .s { font-size: 11.5px; color: var(--text-3); }
</style>
