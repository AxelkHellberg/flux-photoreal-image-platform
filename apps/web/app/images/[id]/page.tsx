import { JobDetailScreen } from "@/components/job-detail-screen";

export default async function ImageDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobDetailScreen jobId={id} />;
}
