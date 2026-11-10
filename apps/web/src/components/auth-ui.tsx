"use client";

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { cx, CutCard, FlaskMark } from "@/components/ui";

export function AuthShell({ title, subtitle, children, footer }: {
  title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-md px-4 py-16 sm:py-24">
      <CutCard innerClassName="p-8">
        <FlaskMark className="h-10 w-10" />
        <h1 className="mt-5 font-display text-2xl font-bold uppercase">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-muted">{subtitle}</p>}
        <div className="mt-8">{children}</div>
      </CutCard>
      {footer && <div className="mt-6 text-center text-sm text-muted">{footer}</div>}
    </div>
  );
}

export function Field({ label, hint, className, ...props }: { label: string; hint?: string } & ComponentProps<"input">) {
  return (
    <label className={cx("block", className)}>
      <span className="fx-label text-muted">{label}</span>
      <input
        {...props}
        className="mt-2 w-full rounded-md border border-line bg-ink px-4 py-3 text-text placeholder:text-dim focus:border-violet focus:outline-none"
      />
      {hint && <span className="mt-1.5 block text-xs text-dim">{hint}</span>}
    </label>
  );
}

export function FormMessage({ kind, children }: { kind: "error" | "ok"; children: ReactNode }) {
  return (
    <p role={kind === "error" ? "alert" : "status"}
      className={cx("rounded-md border px-4 py-3 text-sm",
        kind === "error" ? "border-magenta/50 bg-magenta/10 text-magenta" : "border-cyan/40 bg-cyan/10 text-cyan")}>
      {children}
    </p>
  );
}

export function PrivacyCheckbox() {
  return (
    <label className="flex items-start gap-3 text-sm text-muted">
      <input type="checkbox" name="accept_privacy" required className="mt-1 h-4 w-4 accent-violet" />
      <span>
        Leí y acepto el <Link href="/privacidad" target="_blank" className="text-cyan underline hover:text-white">aviso de privacidad</Link>.
        Usamos tu WhatsApp solo para soporte y avisos de tu cuenta.
      </span>
    </label>
  );
}
