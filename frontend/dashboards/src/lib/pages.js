/* Route → component map. Only built dashboards are registered here; everything
   else falls through to the on-brand Placeholder. Add one line per dashboard as
   it lands (keyed by "<systemId>/<slug>").

   Eager imports keep routing synchronous and bullet-proof for live demos. */

export const pages = {
  // 'smart-routing/overview': SmartRoutingOverview,
  // ...registered incrementally as each dashboard is built.
}

export function pageComponent(systemId, slug) {
  return pages[`${systemId}/${slug}`] || null
}
