/** The product mark: three staggered bars, a miniature witness timeline (same as apps/web). */
export function Mark({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#2A6BE0" />
      <rect x="7" y="8" width="10" height="4" rx="2" fill="#fff" />
      <rect x="12" y="14" width="13" height="4" rx="2" fill="#fff" opacity=".85" />
      <rect x="9" y="20" width="9" height="4" rx="2" fill="#fff" opacity=".65" />
    </svg>
  )
}
