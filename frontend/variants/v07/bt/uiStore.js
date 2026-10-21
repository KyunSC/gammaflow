import { create } from 'zustand'

/** View state that only this design has. Run state stays in lib/backtest/store. */
export const useV7 = create((set) => ({
  holesOnly: false,
  setHolesOnly: (holesOnly) => set({ holesOnly }),
}))
