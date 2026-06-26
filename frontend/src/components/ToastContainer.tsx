import { useToastStore } from '../stores/toastStore'

export function ToastContainer() {
  const { toasts, remove } = useToastStore()

  if (toasts.length === 0) return null

  return (
    <div className="toast-container" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`} onClick={() => remove(t.id)} style={{ cursor: 'pointer' }}>
          {t.message}
        </div>
      ))}
    </div>
  )
}
