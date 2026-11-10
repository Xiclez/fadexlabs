"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState } from "react";

import { cx, Wordmark } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const nav = [
  { href: "/servicios", label: "Servicios" },
  { href: "/portafolio", label: "Portafolio" },
  { href: "/herramientas", label: "Herramientas" },
  { href: "/tienda", label: "Tienda" },
];

function AccountLink({ onClick }: { onClick?: () => void }) {
  const { status, user } = useAuth();
  if (status === "loading") return <span className="h-9 w-24 animate-pulse rounded-full bg-panel-2" aria-hidden />;
  if (status === "authenticated" && user) {
    return (
      <Link href="/cuenta" onClick={onClick}
        className="rounded-full border border-violet/60 px-4 py-2 text-sm font-semibold hover:bg-violet/15">
        {user.display_name.split(" ")[0]}
      </Link>
    );
  }
  return (
    <Link href="/login" onClick={onClick}
      className="rounded-full border border-line px-4 py-2 text-sm font-semibold hover:border-violet">
      Ingresar
    </Link>
  );
}

/** Enlaces del menú de escritorio. `pathname` marca la sección activa. */
function NavLinks({ pathname = "" }: { pathname?: string }) {
  return nav.map((item) => (
    <Link key={item.href} href={item.href}
      className={cx("fx-label rounded px-3 py-2 transition hover:text-white",
        pathname.startsWith(item.href) ? "text-cyan" : "text-muted")}>
      {item.label}
    </Link>
  ));
}

// En rutas dinámicas (/herramientas/trabajos/[id]) la URL solo se conoce al ejecutar: con cacheComponents,
// usePathname() debe ir dentro de <Suspense> para que el resto de la cabecera siga siendo estática.
function ActiveNavLinks() {
  return <NavLinks pathname={usePathname()} />;
}

export function Header() {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-ink/80 backdrop-blur-md">
      <div className="fx-topbar" />
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Wordmark />

        <nav className="hidden items-center gap-1 md:flex" aria-label="Principal">
          <Suspense fallback={<NavLinks />}><ActiveNavLinks /></Suspense>
        </nav>

        <div className="hidden md:block"><AccountLink /></div>

        <button type="button" className="rounded p-2 md:hidden" aria-label={open ? "Cerrar menú" : "Abrir menú"}
          aria-expanded={open} aria-controls="menu-movil" onClick={() => setOpen((o) => !o)}>
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
            {open ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
          </svg>
        </button>
      </div>

      {open && (
        <nav id="menu-movil" className="border-t border-line bg-ink px-4 pb-6 pt-2 md:hidden" aria-label="Principal móvil">
          {nav.map((item) => (
            <Link key={item.href} href={item.href} onClick={close}
              className="fx-label block border-b border-line/60 py-4 text-muted hover:text-white">
              {item.label}
            </Link>
          ))}
          <div className="pt-5"><AccountLink onClick={close} /></div>
        </nav>
      )}
    </header>
  );
}
