"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/auth/SessionContext";
import { labelFor } from "../ui/labels";
import { TopicNavigation } from "../features/chat/TopicNavigation";

interface AuthenticatedShellProps {
  children: ReactNode;
}

const NAVIGATION = [
  { href: "/overview", label: "Обзор", icon: "⌂", adminOnly: false },
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
  const pathname = usePathname() ?? "/";
  const chatMode = pathname === "/" || pathname.startsWith("/chat");
  const { session, signOut } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);

  useEffect(() => {
    if (previousPath.current !== pathname) {
      main.current?.focus();
      previousPath.current = pathname;
    }
  }, [pathname]);

  useEffect(() => {
    if (menuOpen)
      navigation.current
        ?.querySelector<HTMLAnchorElement>("a[aria-current='page'], a")
        ?.focus();
  }, [menuOpen]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key === "Escape" && menuOpen) {
        setMenuOpen(false);
        menuButton.current?.focus();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  return (
    <div className={chatMode ? "app-shell chat-shell" : "app-shell"}>
      <a className="skip-link" href="#main-content">
        Перейти к содержимому
      </a>
      <header className="mobile-bar">
        <button
          ref={menuButton}
          aria-controls="primary-menu"
          aria-expanded={menuOpen}
          aria-label="Открыть меню"
          onClick={() => setMenuOpen(!menuOpen)}
          type="button"
        >
          <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span> Меню
        </button>
        <strong>MANA Operation AI</strong>
      </header>
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
        <nav ref={navigation} aria-label="Основное меню">
          {chatMode ? (
            <TopicNavigation
              pathname={pathname}
              onNavigate={() => {
                setMenuOpen(false);
                main.current?.focus();
              }}
            />
          ) : (
            <>
              <Link className="nav-item" href="/">
                ← К чатам с агентами
              </Link>
              <p className="nav-section-label">Профессиональный режим</p>
            </>
          )}
          {!chatMode &&
            NAVIGATION.map((item) => {
              if (item.adminOnly && session.user.role !== "admin") return null;
              const active =
                pathname === item.href ||
                (item.href === "/growth" && pathname === "/marketing");
              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  className={active ? "nav-item active" : "nav-item"}
                  href={item.href}
                  key={item.href}
                  onClick={() => {
                    setMenuOpen(false);
                    main.current?.focus();
                  }}
                >
                  <span aria-hidden="true">{item.icon}</span>
                  {item.label}
                </Link>
              );
            })}
        </nav>
        {chatMode && (
          <Link
            className="professional-link"
            href="/overview"
            onClick={() => setMenuOpen(false)}
          >
            Профессиональный режим <span aria-hidden="true">↗</span>
          </Link>
        )}
        {!chatMode && (
          <div className="sidebar-safety">
            <div className="pulse-dot" aria-hidden="true" />
            <div>
              <strong>
                {session.live_meta_read_only
                  ? "Meta: только чтение"
                  : "Контролируемые действия"}
              </strong>
              <small>
                {session.live_meta_read_only
                  ? "Изменения в Meta отключены"
                  : "Ограничения · согласование · журнал"}
              </small>
            </div>
          </div>
        )}
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
      <div className="workspace">
        {!chatMode && session.live_meta_read_only ? (
          <div className="live-readonly-banner" role="status">
            <strong>META — ТОЛЬКО ЧТЕНИЕ</strong>
            <span>
              Доступны только рекомендации. Бюджеты, статусы, таргетинг и
              креативы не изменяются.
            </span>
          </div>
        ) : null}
        <main ref={main} id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
