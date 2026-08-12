import { Button } from '../ui/Button'

interface FullToggleProps {
  full: boolean
  onChange: (full: boolean) => void
}

export function FullToggle({ full, onChange }: FullToggleProps) {
  return (
    <Button variant={full ? 'primary' : 'secondary'} onClick={() => onChange(!full)}>
      {full ? 'Showing full detail' : 'Show full detail'}
    </Button>
  )
}
