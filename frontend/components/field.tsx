export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-sm">{label}</span>
      {children}
    </label>
  );
}
