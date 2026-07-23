import { CommandCenter } from "@/components/command-center";

export default async function Page({ params }: { params: Promise<{ view?: string[] }> }) {
  const { view = [] } = await params;
  return <CommandCenter segments={view} />;
}
