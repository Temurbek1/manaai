import Link from "next/link";

export default function NotFound(): React.JSX.Element {
  return (
    <section className="panel route-error">
      <p className="eyebrow">404</p>
      <h1>Страница не найдена</h1>
      <Link className="button" href="/">
        Вернуться к обзору
      </Link>
    </section>
  );
}
