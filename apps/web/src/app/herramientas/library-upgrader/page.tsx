import type { Metadata } from "next";

import { LibraryUpgraderTool } from "@/components/tool-pages";

export const metadata: Metadata = {
  title: "DJ Library Upgrader",
  description: "Sube tu librería en .zip y recíbela en mejor calidad, en el formato que elijas.",
};

export default function LibraryUpgraderPage() {
  return <LibraryUpgraderTool />;
}
