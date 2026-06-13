/* Minimal dependency-free hash router. Exposes a `path` store (e.g.
   "/smart-routing/layer-0") and a `navigate()` helper. Hash-based so the app
   works from any static path with no server rewrites. */

import { writable } from 'svelte/store'

function read() {
  const h = window.location.hash || ''
  const p = h.replace(/^#/, '')
  return p && p !== '/' ? p : '/'
}

export const path = writable(read())

window.addEventListener('hashchange', () => {
  path.set(read())
  // Reset content scroll on every navigation.
  const main = document.querySelector('[data-scroll-main]')
  if (main) main.scrollTop = 0
})

export function navigate(to) {
  const clean = to.replace(/^#/, '')
  const target = '#' + (clean.startsWith('/') ? clean : '/' + clean)
  if (window.location.hash === target) {
    path.set(read())
  } else {
    window.location.hash = target
  }
}
