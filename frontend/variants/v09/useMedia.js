'use client'

import { useEffect, useState } from 'react'

/** 'narrow' under 1024px (stacked document), 'mid' to 1279px (no right rail),
 *  'wide' above. Starts at 'wide' like the original terminal's useWide. */
export default function useMedia() {
  const [media, setMedia] = useState('wide')
  useEffect(() => {
    const lg = window.matchMedia('(min-width: 1024px)')
    const xl = window.matchMedia('(min-width: 1280px)')
    const apply = () => setMedia(xl.matches ? 'wide' : lg.matches ? 'mid' : 'narrow')
    apply()
    lg.addEventListener('change', apply)
    xl.addEventListener('change', apply)
    return () => {
      lg.removeEventListener('change', apply)
      xl.removeEventListener('change', apply)
    }
  }, [])
  return media
}
