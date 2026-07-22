export default function Loading(): React.JSX.Element {
  return (
    <div aria-live="polite" className="loading-state" role="status">
      Loading operational context…
    </div>
  );
}
