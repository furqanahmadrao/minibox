import { create } from 'zustand'

export interface Toast {
  id: string
  type: 'success' | 'error' | 'info'
  message: string
}

interface ToastState {
  toasts: Toast[]
  add: (type: Toast['type'], message: string) => void
  remove: (id: string) => void
}

let counter = 0

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  add: (type, message) => {
    const id = `toast-${++counter}`
    set((s) => ({ toasts: [...s.toasts, { id, type, message }] }))
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 4000)
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
