"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/auth/SessionContext";
import { LanguageSelect } from "@/i18n/LanguageSelect";
import { labelFor } from "../ui/labels";
import { TopicNavigation } from "../features/chat/TopicNavigation";

interface AuthenticatedShellProps {
  children: ReactNode;
}

const NAVIGATION = [
  { href: "/overview", label: "Обзор", icon: "⌂", adminOnly: false },
  {
    href: "/analytics",
    label: "Аналитика и данные",
    icon: "▥",
    adminOnly: false,
  },
  {
    href: "/growth",
    label: "Рост и конверсия",
    icon: "↗",
    adminOnly: false,
  },
  {
    href: "/retention",
    label: "Удержание и лояльность",
    icon: "♡",
    adminOnly: false,
  },
  { href: "/approvals", label: "Согласования", icon: "✓", adminOnly: false },
  { href: "/runs", label: "Запуски и журнал", icon: "≋", adminOnly: false },
  { href: "/agents", label: "Агенты и настройки", icon: "◇", adminOnly: false },
  { href: "/users", label: "Сотрудники и доступ", icon: "◎", adminOnly: true },
] as const;

export function AuthenticatedShell({
  children,
}: AuthenticatedShellProps): React.JSX.Element {
  const { t } = useI18n();

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
    <div
      className={
        chatMode ? "app-shell chat-shell" : "app-shell professional-shell"
      }
    >
      <a className="skip-link" href="#main-content">
        {t("Перейти к содержимому")}{" "}
      </a>
      <header className="mobile-bar">
        <button
          ref={menuButton}
          aria-controls="primary-menu"
          aria-expanded={menuOpen}
          aria-label={t("Открыть меню")}
          onClick={() => setMenuOpen(!menuOpen)}
          type="button"
        >
          <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span>{" "}
          {t("Меню")}{" "}
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
        <nav ref={navigation} aria-label={t("Основное меню")}>
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
                {t("← К чатам с агентами")}{" "}
              </Link>
              <p className="nav-section-label">{t("Профессиональный режим")}</p>
            </>
          )}
          {!chatMode &&
            NAVIGATION.map((item) => {
              if (item.adminOnly && session.user.role !== "admin") return null;
              const active =
                pathname === item.href ||
                (item.href === "/growth" && pathname === "/marketing");
              return (
                <div key={item.href}>
                  {item.href === "/analytics" && (
                    <p className="nav-section-label">
                      {t("Данные и аналитика")}
                    </p>
                  )}
                  {item.href === "/approvals" && (
                    <p className="nav-section-label">{t("Управление")}</p>
                  )}
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={active ? "nav-item active" : "nav-item"}
                    href={item.href}
                    onClick={() => {
                      setMenuOpen(false);
                      main.current?.focus();
                    }}
                  >
                    <span aria-hidden="true">{item.icon}</span>
                    {t(item.label)}
                  </Link>
                </div>
              );
            })}
        </nav>
        {chatMode && (
          <Link
            className="professional-link"
            href="/overview"
            onClick={() => setMenuOpen(false)}
          >
            {t("Профессиональный режим")} <span aria-hidden="true">↗</span>
          </Link>
        )}
        {!chatMode && (
          <div className="sidebar-safety">
            <div className="pulse-dot" aria-hidden="true" />
            <div>
              <strong>
                {session.live_meta_read_only
                  ? t("Meta: только чтение")
                  : t("Контролируемые действия")}
              </strong>
              <small>
                {session.live_meta_read_only
                  ? t("Изменения в Meta отключены")
                  : t("Ограничения · согласование · журнал")}
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
            <small>{t(labelFor(session.user.role))}</small>
          </span>
          <button onClick={() => void signOut()} type="button">
            {t("Выйти")}{" "}
          </button>
        </div>
        <LanguageSelect />
      </aside>
      <div className="workspace">
        {!chatMode && (
          <div className="professional-toolbar">
            <span>
              {t("Администрация")} <span aria-hidden="true">/</span>{" "}
              <strong>
                {t(
                  NAVIGATION.find((item) => item.href === pathname)?.label ??
                    "Профессиональный режим",
                )}
              </strong>
            </span>
            <Link href="/">
              {t("Чаты с агентами")} <span aria-hidden="true">↗</span>
            </Link>
          </div>
        )}
        {!chatMode && session.live_meta_read_only ? (
          <div className="live-readonly-banner" role="status">
            <strong>{t("META — ТОЛЬКО ЧТЕНИЕ")}</strong>
            <span>
              {t(
                "Доступны только рекомендации. Бюджеты, статусы, таргетинг и креативы не изменяются.",
              )}{" "}
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
