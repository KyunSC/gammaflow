import v01 from './v01'
import v02 from './v02'
import v03 from './v03'
import v04 from './v04'
import v05 from './v05'
import v06 from './v06'
import v07 from './v07'
import v08 from './v08'
import v09 from './v09'
import v10 from './v10'

// Keys 1–9 pick variants 01–09 and 0 picks 10; backtick returns to the
// original design. Ordered so the index is the key's position.
export const VARIANTS = [v01, v02, v03, v04, v05, v06, v07, v08, v09, v10]

export const ORIGINAL = 'original'

export const keyToVariantId = (key) => {
  if (key === '`') return ORIGINAL
  if (!/^[0-9]$/.test(key)) return null
  return key === '0' ? '10' : `0${key}`
}

export const findVariant = (id) => VARIANTS.find((v) => v.id === id) || null
