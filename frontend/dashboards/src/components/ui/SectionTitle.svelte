<script>
  let { eyebrow = '', title, children } = $props()
</script>

<div class="sec">
  {#if eyebrow}<div class="eyebrow">{eyebrow}</div>{/if}
  <h2>{title}</h2>
  {#if children}<p class="desc">{@render children()}</p>{/if}
</div>

<style>
  .sec { margin-bottom: 18px; }
  .sec h2 { font-size: 21px; margin-top: 6px; }
  .desc {
    margin-top: 8px;
    color: var(--text-2);
    font-size: 14.5px;
    max-width: 760px;
  }
</style>
