import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Manrope, Unbounded } from "next/font/google";

import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import { AuthProvider } from "@/lib/auth";

import "./globals.css";

const unbounded = Unbounded({ variable: "--font-unbounded", subsets: ["latin"] });
const manrope = Manrope({ variable: "--font-manrope", subsets: ["latin"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  metadataBase: new URL("https://fadexlabs.com"),
  title: {
    default: "FADEX Labs · Audiovisual systems & creative technology",
    template: "%s · FADEX Labs",
  },
  description:
    "Estudio independiente de producción audiovisual y tecnología creativa en Chihuahua, México. DJ sets, VJ, mapping, iluminación DMX, contenido y software para artistas, venues y marcas.",
  openGraph: { siteName: "FADEX Labs", locale: "es_MX", type: "website" },
};

export const viewport: Viewport = { themeColor: "#07080d" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${unbounded.variable} ${manrope.variable} ${jetbrains.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <AuthProvider>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </AuthProvider>
      </body>
    </html>
  );
}
