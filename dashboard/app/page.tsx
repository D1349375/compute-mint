import Dashboard from "@/components/Dashboard";
import { loadBench } from "@/lib/bench";

// The bench file is read per request so a new reference run shows without a rebuild.
export const dynamic = "force-dynamic";

export default async function Page() {
  const bench = await loadBench();
  return <Dashboard bench={bench} />;
}
