/* Route → component map. Only built dashboards are registered here; everything
   else falls through to the on-brand Placeholder. Add one line per dashboard as
   it lands (keyed by "<systemId>/<slug>").

   Eager imports keep routing synchronous and bullet-proof for live demos. */

import SmartRoutingOverview from '../routes/smart-routing/Overview.svelte'
import SmartRoutingLayer0 from '../routes/smart-routing/Layer0.svelte'

export const pages = {
  'smart-routing/overview': SmartRoutingOverview,
  'smart-routing/layer-0': SmartRoutingLayer0,
  // ...registered incrementally as each dashboard is built.
}

export function pageComponent(systemId, slug) {
  return pages[`${systemId}/${slug}`] || null
}
