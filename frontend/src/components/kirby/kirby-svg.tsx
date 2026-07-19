import type { SVGProps } from 'react'

export function KirbySvg(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      {...props}
    >
      <defs>
        <radialGradient id="kirby-body" cx="42%" cy="38%" r="65%">
          <stop offset="0%" stopColor="#ffd6e7" />
          <stop offset="55%" stopColor="#ff9ec4" />
          <stop offset="100%" stopColor="#e46aa0" />
        </radialGradient>
        <radialGradient id="kirby-cheek" cx="50%" cy="50%" r="55%">
          <stop offset="0%" stopColor="#ff7fa8" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#ff7fa8" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Feet */}
      <ellipse cx="34" cy="88" rx="9" ry="5" fill="#c4487a" />
      <ellipse cx="66" cy="88" rx="9" ry="5" fill="#c4487a" />

      {/* Body */}
      <circle cx="50" cy="52" r="38" fill="url(#kirby-body)" />

      {/* Arms */}
      <ellipse cx="14" cy="55" rx="8" ry="6" fill="#ff9ec4" />
      <ellipse cx="86" cy="55" rx="8" ry="6" fill="#ff9ec4" />

      {/* Cheeks */}
      <circle cx="32" cy="58" r="6" fill="url(#kirby-cheek)" />
      <circle cx="68" cy="58" r="6" fill="url(#kirby-cheek)" />

      {/* Eyes */}
      <ellipse cx="41" cy="46" rx="3.2" ry="6" fill="#233047" />
      <ellipse cx="59" cy="46" rx="3.2" ry="6" fill="#233047" />
      <ellipse cx="41" cy="42" rx="1.4" ry="2.4" fill="#ffffff" />
      <ellipse cx="59" cy="42" rx="1.4" ry="2.4" fill="#ffffff" />

      {/* Mouth */}
      <path
        d="M 45 54 Q 50 60 55 54"
        fill="none"
        stroke="#233047"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  )
}
