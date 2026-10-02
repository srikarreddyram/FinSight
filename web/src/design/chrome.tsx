// Always-on brand chrome, rendered once so every screen reads as the same product.
// Colours are FinSight's own: teal accent (the product) and computed-blue (the numbers it checks).
import { C } from './tokens'

/** Fixed colour frame down both viewport edges; never steals a click. */
export function EdgeBezel() {
  const edge = { position: 'fixed', top: 0, bottom: 0, width: 3, opacity: 0.55, zIndex: 40, pointerEvents: 'none' } as const
  return (
    <>
      <div aria-hidden style={{ ...edge, left: 0, background: C.accent }} />
      <div aria-hidden style={{ ...edge, right: 0, background: C.computed }} />
    </>
  )
}

/** Corner-anchored glows, never a full-bleed gradient that would fight the content. */
export function DefaultWash() {
  return (
    <div aria-hidden style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0 }}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(60% 50% at 6% 0%, color-mix(in srgb, ${C.accent} 16%, transparent) 0%, transparent 62%)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(60% 50% at 94% 0%, color-mix(in srgb, ${C.computed} 14%, transparent) 0%, transparent 62%)`,
        }}
      />
    </div>
  )
}

/** Three-band stripe under the header: teal · rule · blue. */
export function HeaderStripe() {
  return (
    <div aria-hidden style={{ position: 'absolute', left: 0, right: 0, bottom: -1, height: 3, display: 'flex' }}>
      <div style={{ flex: 1, background: C.accent }} />
      <div style={{ flex: 1, background: C.rule }} />
      <div style={{ flex: 1, background: C.computed }} />
    </div>
  )
}
