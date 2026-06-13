<script>
  import { path } from './lib/router.js'
  import { resolve } from './lib/registry.js'
  import { pageComponent } from './lib/pages.js'
  import Sidebar from './components/Sidebar.svelte'
  import Home from './routes/Home.svelte'
  import Placeholder from './routes/Placeholder.svelte'

  const isHome = $derived($path === '/' || $path === '')
  const resolved = $derived(isHome ? null : resolve($path))
  const theme = $derived(resolved ? resolved.system.theme : 'theme-routing')
  const Comp = $derived(resolved ? pageComponent(resolved.system.id, resolved.item.slug) : null)
</script>

<div class="layout {theme}">
  <Sidebar current={$path} />
  <main class="content" data-scroll-main>
    <div class="content-inner">
      {#key $path}
        {#if isHome}
          <Home />
        {:else if resolved}
          {#if Comp}
            <Comp />
          {:else}
            <Placeholder system={resolved.system} item={resolved.item} current={$path} />
          {/if}
        {:else}
          <Home />
        {/if}
      {/key}
    </div>
  </main>
</div>

<style>
  .layout { display: flex; height: 100vh; }
  .content { flex: 1; height: 100vh; overflow-y: auto; }
  .content-inner {
    max-width: var(--content-maxw);
    margin: 0 auto;
    padding: 34px 36px 80px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  @media (max-width: 720px) {
    .content-inner { padding: 20px 16px 60px; }
  }
</style>
