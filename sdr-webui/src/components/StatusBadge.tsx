import './status.css';

export function StatusBadge({ tone, label }: { tone: 'green' | 'red' | 'yellow' | 'blue' | 'gray'; label: string }) {
  return <span className={`badge badge-${tone}`}>{label}</span>;
}
