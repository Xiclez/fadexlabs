import Image from "next/image";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { type Accent, accentBorder, type Plan } from "@/content/site";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// ---------- Marca ----------

/** Matraz con ojo, en línea (versión del dossier) para tamaños chicos. */
export function FlaskMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden className={className}>
      <rect x="18" y="3" width="12" height="9" rx="2.5" stroke="var(--color-cyan)" strokeWidth="2" />
      <path d="M20 12 10 36a5 5 0 0 0 4.6 7h18.8A5 5 0 0 0 38 36L28 12" stroke="var(--color-cyan)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M15 31h18" stroke="var(--color-magenta)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="24" cy="25" r="4.5" fill="var(--color-violet)" />
      <circle cx="24" cy="25" r="2" fill="var(--color-cyan)" />
      <circle cx="35" cy="9" r="1.6" fill="var(--color-cyan)" />
      <circle cx="12" cy="18" r="1.6" fill="var(--color-magenta)" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="FADEX Labs, inicio">
      <FlaskMark className="h-8 w-8" />
      <span className="font-display text-[1.05rem] font-semibold tracking-[0.06em]">
        FADEX <span className="font-normal text-muted">LABS</span>
      </span>
    </Link>
  );
}

export function LogoTile({ size = 260 }: { size?: number }) {
  return (
    <div className="relative aspect-square w-full" style={{ maxWidth: size }}>
      <div className="absolute inset-6 rounded-full bg-violet/25 blur-3xl" aria-hidden />
      <Image src="/brand/fadex-logo.jpg" alt="FADEX Labs" width={size} height={size} priority
        className="relative h-auto w-full rounded-2xl bg-logo" />
    </div>
  );
}

// ---------- Tipografía ----------

export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("fx-label text-cyan", className)}>{children}</p>;
}

/** Título de dos líneas: sólido + contorno, como en los catálogos. */
export function DisplayTitle({ solid, outline, as: Tag = "h2", className }: {
  solid: string; outline?: string; as?: "h1" | "h2"; className?: string;
}) {
  return (
    <Tag className={cx("font-display font-bold uppercase leading-[0.95] tracking-tight", className)}>
      <span className="block">{solid}</span>
      {outline && <span className="fx-outline-text block">{outline}</span>}
    </Tag>
  );
}

export function SectionHeader({ label, solid, outline, text, className }: {
  label: string; solid: string; outline?: string; text?: ReactNode; className?: string;
}) {
  return (
    <header className={cx("mb-10 max-w-3xl", className)}>
      <Label className="mb-4">{label}</Label>
      <DisplayTitle solid={solid} outline={outline} className="text-3xl sm:text-5xl" />
      {text && <p className="mt-5 text-lg text-muted">{text}</p>}
    </header>
  );
}

export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("mx-auto w-full max-w-6xl px-4 sm:px-6", className)}>{children}</div>;
}

// ---------- Botones ----------

type BtnProps = { variant?: "primary" | "ghost"; className?: string; children: ReactNode };

const btnBase = "inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-semibold tracking-wide transition";
const btnVariants = {
  primary: "bg-linear-to-r from-magenta via-violet to-cyan text-white fx-glow hover:brightness-110",
  ghost: "border border-line text-text hover:border-violet hover:text-white",
};

export function ButtonLink({ variant = "primary", className, children, ...props }: BtnProps & ComponentProps<typeof Link>) {
  return <Link className={cx(btnBase, btnVariants[variant], className)} {...props}>{children}</Link>;
}

export function Button({ variant = "primary", className, children, ...props }: BtnProps & ComponentProps<"button">) {
  return (
    <button className={cx(btnBase, btnVariants[variant], "disabled:cursor-not-allowed disabled:opacity-50", className)} {...props}>
      {children}
    </button>
  );
}

// ---------- Tarjetas ----------

export function CutCard({ children, className, innerClassName }: {
  children: ReactNode; className?: string; innerClassName?: string;
}) {
  return (
    <div className={cx("fx-cut", className)}>
      <div className={cx("fx-cut-inner p-6", innerClassName)}>{children}</div>
    </div>
  );
}

export function PanelCard({ title, text, accent }: { title: string; text: string; accent: Accent }) {
  return (
    <div className={cx("fx-panel p-5", accentBorder[accent])}>
      <h3 className="font-display text-sm font-semibold uppercase tracking-wide">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted">{text}</p>
    </div>
  );
}

export function PlanCard({ plan, index }: { plan: Plan; index: number }) {
  return (
    <CutCard className={cx("h-full", plan.highlight && "fx-glow")} innerClassName="flex h-full flex-col">
      <div className="flex items-center justify-between">
        <span className="fx-label text-violet">{String(index + 1).padStart(2, "0")}</span>
        <span className="fx-label text-dim">//</span>
      </div>
      <h3 className="mt-3 font-display text-base font-semibold uppercase">{plan.name}</h3>
      {plan.subtitle && <p className="fx-label mt-1 text-muted">{plan.subtitle}</p>}
      <p className="mt-5 flex flex-wrap items-baseline gap-x-2 border-y border-line py-4">
        <span className="fx-gradient-text font-display text-3xl font-bold">{plan.price}</span>
        {plan.unit && <span className="fx-label text-muted">{plan.unit}</span>}
      </p>
      <ul className="mt-4 space-y-2 text-sm text-text/90">
        {plan.features.map((f) => (
          <li key={f} className="flex gap-2">
            <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rotate-45 bg-cyan" />
            {f}
          </li>
        ))}
      </ul>
      {plan.idealFor && (
        <p className="mt-auto pt-5 text-xs leading-relaxed text-muted">
          <span className="fx-label mr-1 text-magenta">Ideal para</span> {plan.idealFor}
        </p>
      )}
    </CutCard>
  );
}

export function Pill({ children }: { children: ReactNode }) {
  return <span className="rounded-full border border-line px-3 py-1 text-xs text-muted">{children}</span>;
}
