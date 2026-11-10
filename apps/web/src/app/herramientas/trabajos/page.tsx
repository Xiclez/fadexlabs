import type { Metadata } from "next";

import { JobList } from "@/components/job-views";

export const metadata: Metadata = { title: "Mis trabajos", robots: { index: false } };

export default function TrabajosPage() {
  return <JobList />;
}
