// Audio-level bars for the Processing hero: an animated equalizer while
// the job is active, a static staircase otherwise — and under reduced
// motion the index.css kill switch ends the animation and .eq-bar's base
// transform takes over (same fallback as .orbit-glyph). Purely decorative;
// the screen-reader story lives in CyclingStatusMessage's live region.

import type { CSSProperties } from 'react'

const BAR_COUNT = 5

export function EqualizerBars({ active }: { active: boolean }) {
  return (
    <div aria-hidden className="flex h-6 items-end gap-[3px]">
      {Array.from({ length: BAR_COUNT }, (_, i) => (
        <span
          key={i}
          className={`eq-bar h-full w-[3px] rounded-full transition-colors duration-200 ${
            active ? 'eq-bar-active bg-accent' : 'bg-line'
          }`}
          style={{ '--i': i } as CSSProperties}
        />
      ))}
    </div>
  )
}
