import { LANE_NAMES, type Lang } from "@/lib/i18n";
import type { Lane } from "@/lib/types";

export default function LaneChip({ lane, lang }: { lane: Lane; lang: Lang }) {
  return (
    <span className={`chip lane-${lane}`}>
      <span className="sw" aria-hidden />
      {LANE_NAMES[lang][lane]}
    </span>
  );
}
