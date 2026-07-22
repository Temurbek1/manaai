import Link from "next/link";

export default function NotFound(): React.JSX.Element {
  return (
    <section className="panel route-error">
      <p className="eyebrow">404</p>
      <h1>Control-room route not found</h1>
      <Link className="button" href="/">
        Return to overview
      </Link>
    </section>
  );
}
