export function ViewerProgress({
  compact = false,
  label,
  progress,
}: {
  compact?: boolean;
  label: string;
  progress: number | null;
}) {
  const percent =
    progress == null ? null : Math.max(0, Math.min(100, progress));
  return (
    <div
      aria-label={
        percent == null ? `${label}, starting` : `${label}, ${percent}%`
      }
      className={`viewer-progress${compact ? " compact" : ""}`}
      role="status"
    >
      <div className="viewer-progress-copy">
        <span>{label}</span>
        <strong>{percent == null ? "STARTING" : `${percent}%`}</strong>
      </div>
      <div
        aria-hidden="true"
        className={`viewer-progress-track${
          percent == null ? " indeterminate" : ""
        }`}
      >
        <i style={percent == null ? undefined : { width: `${percent}%` }} />
      </div>
    </div>
  );
}
