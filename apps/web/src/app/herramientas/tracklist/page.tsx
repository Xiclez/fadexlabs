import type { Metadata } from "next";

import { TracklistTool } from "@/components/tool-pages";

export const metadata: Metadata = {
  title: "Tracklist ID",
  description: "Sube tu DJ set y recibe el tracklist con timestamps.",
};

export default function TracklistPage() {
  return <TracklistTool />;
}
