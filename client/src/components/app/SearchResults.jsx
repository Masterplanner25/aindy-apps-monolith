import { safeMap } from "../../utils/safe";

function toPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.round(Number(value) * 100);
}

function ScoreBadge({ value, label = "score", tone = "emerald" }) {
  const pct = toPercent(value);
  if (pct === null) return null;
  const tones = {
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    blue: "bg-blue-500/10 text-blue-300 border-blue-500/30",
    zinc: "bg-zinc-700/40 text-zinc-300 border-zinc-600/40",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${tones[tone] || tones.zinc}`}
      title={`${label}: ${pct}%`}
    >
      {label} {pct}
    </span>
  );
}

/**
 * Renders a unified, ranked SearchResponse.results list (Evolution Plan — v5).
 * Each item follows the shared SearchResultItem shape: { title, url, snippet,
 * score, metadata: { relevance, quality_score, ... } }.
 */
export default function SearchResults({ results = [], searchScore = null, title = "Ranked Results" }) {
  if (!Array.isArray(results) || results.length === 0) return null;

  return (
    <div className="border border-zinc-800 rounded-lg bg-zinc-950/70 p-4 mt-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
        <ScoreBadge value={searchScore} label="overall" tone="blue" />
      </div>

      <ol className="space-y-2">
        {safeMap(results, (item, index) => (
          <li
            key={item.url || `${item.title}-${index}`}
            className="border border-zinc-800 rounded-md p-3 bg-zinc-900/70"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-zinc-600 font-mono">#{index + 1}</span>
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-blue-400 hover:text-blue-300 truncate"
                    >
                      {item.title}
                    </a>
                  ) : (
                    <span className="text-sm text-zinc-100 truncate">{item.title}</span>
                  )}
                </div>
                {item.snippet ? (
                  <p className="text-xs text-zinc-400 mt-1 leading-relaxed">{item.snippet}</p>
                ) : null}
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <ScoreBadge value={item.score} label="rank" tone="emerald" />
                <ScoreBadge value={item.metadata?.relevance} label="rel" tone="zinc" />
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
