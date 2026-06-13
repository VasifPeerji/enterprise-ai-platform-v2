<script>
  let {
    variant = 'primary', // primary | ghost | soft
    type = 'button',
    disabled = false,
    onclick,
    children,
  } = $props()
</script>

<button class="btn {variant}" {type} {disabled} {onclick}>
  {@render children()}
</button>

<style>
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    padding: 10px 18px;
    font-size: 14px;
    font-weight: 620;
    transition: transform 0.08s ease, filter 0.15s ease, background 0.15s ease;
  }
  .btn:active { transform: translateY(1px); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .primary {
    background: linear-gradient(95deg, var(--accent-1), var(--accent-2));
    color: var(--text-on-accent);
  }
  .primary:not(:disabled):hover { filter: brightness(1.08); }
  .soft {
    background: var(--accent-soft);
    color: var(--accent-2);
    border-color: var(--accent-line);
  }
  .soft:not(:disabled):hover { background: var(--surface-hover); }
  .ghost {
    background: var(--surface-2);
    color: var(--text-1);
    border-color: var(--border-2);
  }
  .ghost:not(:disabled):hover { background: var(--surface-hover); }
</style>
