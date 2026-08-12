interface SpinnerProps {
  size?: 'sm' | 'md'
}

export function Spinner({ size = 'md' }: SpinnerProps) {
  const dimension = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5'
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block ${dimension} animate-spin rounded-full border-2 border-current border-t-transparent opacity-70`}
    />
  )
}
