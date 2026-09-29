"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { useSession } from "@/auth/SessionContext";
import { labelFor } from "../ui/labels";

interface AuthenticatedShellProps {
  children: ReactNode;
}

const NAVIGATION = [
  { href: "/", label: "Обзор", icon: "⌂", adminOnly: false },
  {
    href: "/growth",
    label: "Рост и конверсия",
    icon: "↗",
    adminOnly: false,
  },
  { href: "/approvals", label: "Согласования", icon: "✓", adminOnly: false },
  {
    href: "/retention",
    label: "Удержание и лояльность",
    icon: "♡",
    adminOnly: false,
  },
  { href: "/runs", label: "Запуски и журнал", icon: "≋", adminOnly: false },
  { href: "/agents", label: "Агенты и настройки", icon: "◇", adminOnly: false },
  { href: "/users", label: "Сотрудники и доступ", icon: "◎", adminOnly: true },
] as const;

export function AuthenticatedShell({
  children,
}: AuthenticatedShellProps): React.JSX.Element {
  const pathname = usePathname();
  const { session, signOut } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  return (
    <div className="app-shell">
      <aside
        className={menuOpen ? "sidebar open" : "sidebar"}
        id="primary-menu"
      >
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>MANA</strong>
            <small>Operation AI</small>
          </div>
        </div>
        <nav aria-label="Основное меню">
          {NAVIGATION.map((item) => {
            if (item.adminOnly && session.user.role !== "admin") return null;
            const active = pathname === item.href;
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={active ? "nav-item active" : "nav-item"}
                href={item.href}
                key={item.href}
                onClick={() => setMenuOpen(false)}
              >
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-safety">
          <div className="pulse-dot" aria-hidden="true" />
          <div>
            <strong>
              {session.live_meta_read_only
                ? "Реальные данные: только чтение"
                : "Контролируемые действия"}
            </strong>
            <small>
              {session.live_meta_read_only
                ? "Изменения в Meta отключены"
                : "Ограничения · согласование · журнал"}
            </small>
          </div>
        </div>
        <div className="session-box">
          <span>
            <strong>
              {session.user.display_name ??
                session.user.username ??
                String(session.user.telegram_id)}
            </strong>
            <small>{labelFor(session.user.role)}</small>
          </span>
          <button onClick={() => void signOut()} type="button">
            Выйти
          </button>
        </div>
      </aside>
      {menuOpen ? (
        <button
          aria-label="Закрыть меню"
          className="scrim"
          onClick={() => setMenuOpen(false)}
          type="button"
        />
      ) : null}
      <div className="workspace">
        {session.live_meta_read_only ? (
          <div className="live-readonly-banner" role="status">
            <strong>META — ТОЛЬКО ЧТЕНИЕ</strong>
            <span>
              Доступны только рекомендации. Бюджеты, статусы, таргетинг и
              креативы не изменяются.
            </span>
          </div>
        ) : null}
        <header className="mobile-bar">
          <button
            aria-controls="primary-menu"
            aria-expanded={menuOpen}
            aria-label="Открыть меню"
            onClick={() => setMenuOpen(true)}
            type="button"
          >
            ☰
          </button>
          <strong>MANA Operation AI</strong>
          <span className="pulse-dot" aria-hidden="true" />
        </header>
        <main>{children}</main>
      </div>
    </div>
  );
}
