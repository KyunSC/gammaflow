# UI variants

Ten alternative designs of the whole frontend live side by side in one build.
Press a key to switch the live page:

| Key | Design |
| --- | --- |
| 1 – 9 | variants 01 – 09 |
| 0 | variant 10 |
| ` (backtick) | the original design |

`?ui=03` in the URL picks a variant directly (`?ui=original` for the
original), and `?badge=0` hides the corner label for clean screenshots. The
choice is remembered in localStorage. Keys are ignored while an input,
select, textarea or contenteditable has focus, and when Cmd/Ctrl/Alt is held.
Because plain digits now belong to the switcher, the backtester's strategy
family hotkeys moved from 1–4 to Alt+1–4.

## Contract for a variant

Everything for variant `NN` lives in `variants/vNN/`. Its `index.js` default
export is:

```js
import dynamic from 'next/dynamic'

const variant = {
  id: 'NN',
  name: 'Two-word name',
  Home: dynamic(() => import('./Home')),                       // replaces app/page.jsx
  Ticker: dynamic(() => import('./Ticker')),                   // gets { params } like app/ticker/[symbol]/page.jsx
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),// replaces the BacktestTerminal on /backtest
}
export default variant
```

Any slot left out falls back to the original page.

- Don't edit files outside `variants/vNN/`. Copy a shared component into the
  variant folder and change the copy. Importing shared components and
  `lib/` unchanged is fine.
- CSS stays scoped: CSS modules, or plain CSS whose every selector starts with
  `:root[data-ui="NN"]` (the switcher sets `data-ui` on `<html>`). Variant CSS
  stays loaded after switching away, so unscoped rules leak into the others.
  No `@theme`, `@import 'tailwindcss…'` or other global declarations.
- Tailwind utilities are generated only on `/backtest` (from
  `app/backtest/backtest.css`, which already scans `variants/`). Pages outside
  /backtest need their own scoped CSS.
- `next/font` at module scope in the variant's own files is fine.
- The backtester state lives in `lib/backtest/store.js` (zustand), so every
  variant shares the same run, strategy and settings when you switch.
