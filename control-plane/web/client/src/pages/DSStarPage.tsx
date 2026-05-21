import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Upload,
  FileSpreadsheet,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Trash2,
  Microscope,
  ChevronDown,
  ChevronUp,
  Code2,
  FileText,
  BarChart3,
  Image,
  Layers,
  Timer,
  Zap,
  Download,
} from "lucide-react";
import { WorkflowDAGViewer } from "@/components/WorkflowDAG";
import { StepDetail } from "@/components/StepDetail";
import { getWorkflowDAGLightweight } from "@/services/workflowsApi";
import { dsStarApi } from "@/services/dsStarApi";
import type { ChartData } from "@/services/dsStarApi";
import type { AsyncExecuteResponse, ExecutionStatusResponse } from "@/types/execution";
import type { WorkflowDAGLightweightResponse } from "@/types/workflows";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { marked } from "marked";

type PipelinePhase = "idle" | "uploading" | "running" | "completed" | "error";

interface UploadedFile {
  name: string;
  size: number;
  status: "uploading" | "done" | "error";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileUploadZone({
  files,
  onFilesAdded,
  onRemove,
  disabled,
}: {
  files: UploadedFile[];
  onFilesAdded: (files: File[]) => void;
  onRemove: (name: string) => void;
  disabled: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const dropped = Array.from(e.dataTransfer.files).filter(
        (f) => f.name.endsWith(".csv") || f.name.endsWith(".xlsx") || f.name.endsWith(".json")
      );
      if (dropped.length > 0) onFilesAdded(dropped);
    },
    [onFilesAdded, disabled]
  );

  const handleSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files ? Array.from(e.target.files) : [];
      if (selected.length > 0) onFilesAdded(selected);
      if (inputRef.current) inputRef.current.value = "";
    },
    [onFilesAdded]
  );

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={cn(
          "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
          dragOver
            ? "border-primary bg-primary/5"
            : "border-border/60 hover:border-primary/40 hover:bg-muted/30",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-sm font-medium text-foreground">
          Drop CSV, XLSX, or JSON files here
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          or click to browse
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.json"
          multiple
          onChange={handleSelect}
          className="hidden"
          disabled={disabled}
        />
      </div>

      {files.length > 0 && (
        <div className="space-y-1.5">
          {files.map((f) => (
            <div
              key={f.name}
              className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/40 border border-border/40"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileSpreadsheet className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-sm truncate">{f.name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatBytes(f.size)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {f.status === "uploading" && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                )}
                {f.status === "done" && (
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                )}
                {f.status === "error" && (
                  <XCircle className="h-3.5 w-3.5 text-destructive" />
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(f.name);
                  }}
                  disabled={disabled || f.status === "uploading"}
                  className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChartsGrid({ charts }: { charts: ChartData[] }) {
  const [selectedChart, setSelectedChart] = useState<string | null>(null);

  if (charts.length === 0) return null;

  return (
    <Card variant="surface" interactive={false}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Image className="h-4 w-4" />
          Visualizations ({charts.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3">
          {charts.map((chart) => (
            <button
              key={chart.name}
              onClick={() => setSelectedChart(selectedChart === chart.name ? null : chart.name)}
              className={cn(
                "border rounded-lg overflow-hidden transition-all hover:ring-2 hover:ring-primary/40",
                selectedChart === chart.name ? "ring-2 ring-primary col-span-2" : "border-border/40"
              )}
            >
              <img
                src={chart.data}
                alt={chart.name}
                className="w-full h-auto bg-white"
                loading="lazy"
              />
              <div className="px-2 py-1.5 bg-muted/40 text-xs text-muted-foreground truncate">
                {chart.name}
              </div>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function StrategySummary({ data }: { data: Record<string, any> }) {
  const strategies = data.strategies_explored;
  const elapsed = data.elapsed_seconds;

  if (!strategies && elapsed == null) return null;

  return (
    <div className="grid grid-cols-2 gap-3">
      {strategies != null && (
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className="text-xl font-bold text-primary">
              {strategies}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1 flex items-center justify-center gap-1">
              <Layers className="h-2.5 w-2.5" />
              Strategies
            </div>
          </CardContent>
        </Card>
      )}
      {elapsed != null && (
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className="text-xl font-bold">
              {elapsed < 60 ? `${Math.round(elapsed)}s` : `${Math.floor(elapsed / 60)}m ${Math.round(elapsed % 60)}s`}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1 flex items-center justify-center gap-1">
              <Timer className="h-2.5 w-2.5" />
              Elapsed
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

async function buildReportHTML(
  data: Record<string, any>,
): Promise<string> {
  let markdown = data.final_answer || "";

  // Build chart lookup from pipeline result (base64 data URLs embedded by backend)
  const chartEmbeds: Map<string, string> = new Map();
  const chartArr: Array<{ name: string; data: string }> = data.charts ?? [];
  for (const c of chartArr) {
    if (c.name && c.data) chartEmbeds.set(c.name, c.data);
  }

  const score = data.run_score != null
    ? (typeof data.run_score === "object" ? (data.run_score as any).score : data.run_score)
    : null;

  // Replace markdown image refs with inline base64 <img> tags
  const referencedCharts = new Set<string>();
  for (const [filename, dataUrl] of chartEmbeds) {
    const escaped = filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    referencedCharts.add(filename);
    markdown = markdown.replace(
      new RegExp(`!\\[([^\\]]*)\\]\\(charts/${escaped}\\)`, "g"),
      `<img src="${dataUrl}" alt="$1" style="max-width:100%;border-radius:8px;margin:12px 0;display:block;" />`
    );
  }

  // Convert markdown to HTML using marked (proper GFM tables, code blocks, lists)
  const bodyHTML = await marked.parse(markdown, { gfm: true, breaks: false });

  // Charts gallery (any chart not already referenced in the report)
  const unreferencedCharts = [...chartEmbeds.entries()].filter(([n]) => !referencedCharts.has(n));
  const galleryHTML = unreferencedCharts.length > 0
    ? `<h2>Additional Charts</h2>
       <div class="chart-grid">
         ${unreferencedCharts.map(([n, url]) => `<div class="chart-card">
           <img src="${url}" alt="${n}" />
           <div class="chart-label">${n}</div>
         </div>`).join("\n")}
       </div>`
    : "";

  const plansHTML = data.plans?.length
    ? `<h2>Analysis Plan</h2><ol class="plan-list">${data.plans.map((s: string, i: number) =>
        `<li><span class="step-num">${i + 1}</span>${s}</li>`).join("")}</ol>`
    : "";

  const codeHTML = data.final_code
    ? `<details class="code-section"><summary>Generated Code</summary>
       <pre><code>${data.final_code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre></details>`
    : "";

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DS Star Analysis Report</title>
<style>
  :root { --bg: #ffffff; --fg: #1f2937; --fg-dim: #6b7280; --fg-muted: #4b5563; --border: #e5e7eb; --surface: #f9fafb; --accent: #6366f1; --green: #16a34a; --amber: #d97706; --red: #dc2626; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.7; color: var(--fg); max-width: 920px; margin: 0 auto; padding: 48px 28px; background: var(--bg); }
  h1 { font-size: 26px; font-weight: 700; margin: 32px 0 8px; color: #111827; }
  h2 { font-size: 20px; font-weight: 600; margin: 36px 0 14px; color: #111827; border-bottom: 2px solid var(--border); padding-bottom: 8px; }
  h3 { font-size: 16px; font-weight: 600; margin: 24px 0 10px; color: #374151; }
  h4 { font-size: 14px; font-weight: 600; margin: 18px 0 8px; color: #374151; }
  p { margin-bottom: 14px; color: var(--fg-muted); font-size: 15px; }
  ul, ol { margin: 8px 0 16px 24px; color: var(--fg-muted); font-size: 15px; }
  li { margin-bottom: 6px; line-height: 1.6; }
  a { color: var(--accent); text-decoration: none; }
  strong { color: #111827; font-weight: 600; }
  em { color: var(--fg-muted); }
  hr { border: none; border-top: 1px solid var(--border); margin: 32px 0; }
  img { max-width: 100%; border-radius: 8px; margin: 16px 0; display: block; }

  /* Tables */
  table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }
  th, td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; }
  th { background: var(--surface); font-weight: 600; color: #374151; font-size: 13px; text-transform: uppercase; letter-spacing: 0.03em; }
  tr:nth-child(even) { background: #fafafa; }
  tr:hover { background: #f3f4f6; }

  /* Code */
  code { background: #f3f4f6; padding: 2px 7px; border-radius: 4px; font-size: 13px; font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; color: #c7254e; }
  pre { background: #1e1e2e; color: #cdd6f4; padding: 20px; border-radius: 10px; overflow-x: auto; font-size: 13px; line-height: 1.6; margin: 16px 0; }
  pre code { background: none; padding: 0; color: inherit; font-size: inherit; }

  /* Blockquote */
  blockquote { border-left: 4px solid var(--accent); padding: 12px 20px; margin: 16px 0; background: #f5f3ff; color: #4338ca; border-radius: 0 8px 8px 0; }
  blockquote p { color: #4338ca; margin-bottom: 4px; }

  /* Stats dashboard */
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 28px 0; }
  .stat { text-align: center; padding: 18px 12px; background: var(--surface); border-radius: 10px; border: 1px solid var(--border); }
  .stat-value { font-size: 28px; font-weight: 700; line-height: 1.2; }
  .stat-label { font-size: 11px; color: var(--fg-dim); margin-top: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
  .green { color: var(--green); } .amber { color: var(--amber); } .red { color: var(--red); } .blue { color: var(--accent); }

  .header-meta { color: var(--fg-dim); font-size: 14px; margin-bottom: 4px; }

  /* Charts gallery */
  .chart-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 20px 0; }
  .chart-card { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .chart-card img { border-radius: 0; margin: 0; width: 100%; display: block; }
  .chart-label { padding: 8px 12px; font-size: 12px; color: var(--fg-dim); background: var(--surface); }

  /* Plan list */
  .plan-list { list-style: none; margin-left: 0; counter-reset: none; }
  .plan-list li { display: flex; gap: 12px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }
  .step-num { flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: white; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; }

  /* Code section */
  .code-section { margin: 20px 0; }
  .code-section summary { cursor: pointer; font-weight: 600; font-size: 16px; padding: 12px 0; color: #374151; }
  .code-section summary:hover { color: var(--accent); }

  @media print {
    body { padding: 20px; }
    .stats { break-inside: avoid; }
    pre { white-space: pre-wrap; word-wrap: break-word; }
    img { break-inside: avoid; max-width: 100%; }
    table { break-inside: avoid; }
    h2, h3 { break-after: avoid; }
    .chart-grid { break-inside: avoid; }
    .chart-card { break-inside: avoid; }
    .code-section { break-inside: avoid; }
    .plan-list li { break-inside: avoid; }
  }
</style>
</head>
<body>
<h1>DS Star Analysis Report</h1>
<p class="header-meta">Generated ${new Date().toLocaleString()} &middot; ${data.strategies_explored ?? "-"} strategies &middot; ${data.total_ai_calls ?? "-"} AI calls${data.elapsed_seconds ? ` &middot; ${Math.round(data.elapsed_seconds)}s` : ""}</p>

<div class="stats">
  <div class="stat"><div class="stat-value">${data.iterations ?? "-"}</div><div class="stat-label">Iterations</div></div>
  <div class="stat"><div class="stat-value blue">${data.total_ai_calls ?? "-"}</div><div class="stat-label">AI Calls</div></div>
  <div class="stat"><div class="stat-value ${data.verified ? "green" : "amber"}">${data.verified ? "Yes" : "No"}</div><div class="stat-label">Verified</div></div>
  <div class="stat"><div class="stat-value ${score != null && score >= 0.7 ? "green" : score != null && score >= 0.4 ? "amber" : "red"}">${score != null ? Number(score).toFixed(2) : "-"}</div><div class="stat-label">Score</div></div>
</div>

${bodyHTML}

${galleryHTML}
${plansHTML}
${codeHTML}

<hr />
<p style="font-size:12px;color:#9ca3af;text-align:center;">Generated by DS Star &mdash; AgentField Data Science Agent</p>
</body>
</html>`;
}

function ResultsPanel({ result, charts }: { result: ExecutionStatusResponse | null; charts: ChartData[] }) {
  const [codeOpen, setCodeOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  if (!result?.result) return null;

  const data = result.result;
  const rawScore = typeof data.run_score === "object" && data.run_score !== null
    ? (data.run_score as Record<string, unknown>).score
    : data.run_score;
  const score = rawScore != null ? Number(rawScore) : NaN;

  return (
    <div className="space-y-4">
      <StrategySummary data={data} />

      <div className="grid grid-cols-4 gap-2">
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className="text-xl font-bold">
              {data.iterations ?? "-"}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">Iterations</div>
          </CardContent>
        </Card>
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className="text-xl font-bold text-primary">
              {data.total_ai_calls ?? "-"}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1 flex items-center justify-center gap-0.5">
              <Zap className="h-2.5 w-2.5" />
              AI Calls
            </div>
          </CardContent>
        </Card>
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className={cn("text-xl font-bold", data.verified ? "text-green-500" : "text-amber-500")}>
              {data.verified ? "Yes" : "No"}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">Verified</div>
          </CardContent>
        </Card>
        <Card variant="muted" interactive={false}>
          <CardContent className="p-3 text-center">
            <div className={cn(
              "text-xl font-bold",
              !isNaN(score) && score >= 0.7 ? "text-green-500" : !isNaN(score) && score >= 0.4 ? "text-amber-500" : "text-destructive"
            )}>
              {!isNaN(score) ? score.toFixed(2) : "-"}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">Score</div>
          </CardContent>
        </Card>
      </div>

      {data.final_answer && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Final Answer
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                disabled={downloading}
                onClick={async () => {
                  setDownloading(true);
                  try {
                    const html = await buildReportHTML(data);
                    const printWin = window.open("", "_blank");
                    if (printWin) {
                      printWin.document.write(html);
                      printWin.document.close();
                      printWin.addEventListener("load", () => printWin.print());
                      setTimeout(() => printWin.print(), 600);
                    }
                  } finally {
                    setDownloading(false);
                  }
                }}
                className="h-7 text-xs gap-1.5"
              >
                {downloading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                Save as PDF
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm max-w-none prose-invert prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-code:text-foreground prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => <h1 className="text-lg font-semibold mb-3 mt-4 first:mt-0 text-foreground border-b border-border pb-2">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0 text-foreground">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-medium mb-2 mt-2 text-foreground">{children}</h3>,
                  p: ({ children }) => <p className="mb-2 text-sm leading-relaxed text-muted-foreground">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc list-inside mb-3 text-sm space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-3 text-sm space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="leading-relaxed text-muted-foreground">{children}</li>,
                  strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="text-muted-foreground">{children}</em>,
                  table: ({ children }) => (
                    <div className="overflow-auto mb-3 border border-border rounded-lg">
                      <table className="min-w-full text-sm">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                  th: ({ children }) => (
                    <th className="border-b border-border px-3 py-2 text-left text-xs font-semibold text-foreground uppercase tracking-wider">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border-b border-border/50 px-3 py-2 text-sm text-muted-foreground">
                      {children}
                    </td>
                  ),
                  tr: ({ children }) => <tr className="hover:bg-muted/30 transition-colors">{children}</tr>,
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-4 border-accent-primary pl-3 italic text-muted-foreground mb-2 bg-muted/30 py-1 rounded-r">
                      {children}
                    </blockquote>
                  ),
                  code: ({ children, className }) => {
                    const isBlock = className?.includes("language-");
                    return isBlock ? (
                      <code className={className}>{children}</code>
                    ) : (
                      <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono text-foreground border border-border">
                        {children}
                      </code>
                    );
                  },
                  pre: ({ children }) => (
                    <pre className="bg-muted/50 border border-border rounded-lg p-3 text-xs overflow-x-auto mb-3 font-mono">
                      {children}
                    </pre>
                  ),
                  hr: () => <hr className="border-border my-4" />,
                }}
              >
                {data.final_answer}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      )}

      {data.final_code && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <button
              onClick={() => setCodeOpen(!codeOpen)}
              className="flex items-center gap-2 text-sm font-semibold w-full text-left"
            >
              <Code2 className="h-4 w-4" />
              Generated Code
              {codeOpen ? (
                <ChevronUp className="h-3.5 w-3.5 ml-auto" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 ml-auto" />
              )}
            </button>
          </CardHeader>
          {codeOpen && (
            <CardContent>
              <pre className="text-xs bg-muted/50 border border-border rounded-lg p-4 overflow-x-auto max-h-96 font-mono leading-relaxed">
                <code>{data.final_code}</code>
              </pre>
            </CardContent>
          )}
        </Card>
      )}

      <ChartsGrid charts={charts} />

      {data.plans && data.plans.length > 0 && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Analysis Plan ({data.plans.length} steps)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="text-sm space-y-2 list-none">
              {data.plans.map((step: string, i: number) => (
                <li key={i} className="flex gap-3 text-muted-foreground">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-foreground">
                    {i + 1}
                  </span>
                  <span className="leading-relaxed pt-0.5">{step}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export function DSStarPage() {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [query, setQuery] = useState("");
  const [maxIterations, setMaxIterations] = useState(20);
  const [guidelines, setGuidelines] = useState("");
  const [numStrategies, setNumStrategies] = useState(5);
  const [strategyMaxIters, setStrategyMaxIters] = useState(5);
  const [numCodeVariants, setNumCodeVariants] = useState(3);
  const [numVerifiers, setNumVerifiers] = useState(3);
  const [phase, setPhase] = useState<PipelinePhase>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [charts, setCharts] = useState<ChartData[]>([]);

  const [executionId, setExecutionId] = useState<string | null>(null);
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const readyFiles = files.filter((f) => f.status === "done").map((f) => f.name);
  const canExecute =
    phase !== "running" &&
    phase !== "uploading" &&
    readyFiles.length > 0 &&
    query.trim().length > 0;

  // Fetch uploaded files on mount
  useEffect(() => {
    dsStarApi.listFiles().then((remote) => {
      if (remote.length > 0) {
        setFiles((prev) => {
          const existing = new Set(prev.map((f) => f.name));
          const merged = [...prev];
          for (const rf of remote) {
            if (!existing.has(rf.name)) {
              merged.push({ name: rf.name, size: rf.size, status: "done" });
            }
          }
          return merged;
        });
      }
    });
  }, []);

  const handleFilesAdded = useCallback(async (newFiles: File[]) => {
    const entries: UploadedFile[] = newFiles.map((f) => ({
      name: f.name,
      size: f.size,
      status: "uploading" as const,
    }));
    setFiles((prev) => [...prev, ...entries]);
    setPhase("uploading");

    for (const file of newFiles) {
      try {
        await dsStarApi.uploadFile(file);
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "done" as const } : f
          )
        );
      } catch {
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "error" as const } : f
          )
        );
      }
    }
    setPhase("idle");
  }, []);

  const handleRemoveFile = useCallback((name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }, []);

  const handleExecute = useCallback(async () => {
    if (!canExecute) return;
    setPhase("running");
    setErrorMsg(null);
    setExecutionId(null);
    setWorkflowId(null);
    setRunId(null);
    setSelectedStepId(null);

    try {
      const resp: AsyncExecuteResponse = await dsStarApi.executePipeline({
        query: query.trim(),
        data_files: readyFiles,
        max_iterations: maxIterations,
        guidelines: guidelines.trim() || undefined,
        num_strategies: numStrategies,
        strategy_max_iters: strategyMaxIters,
        num_code_variants: numCodeVariants,
        num_verifiers: numVerifiers,
      });
      setExecutionId(resp.execution_id);
      setWorkflowId(resp.workflow_id);
      setRunId(resp.run_id ?? resp.workflow_id);
    } catch (err: any) {
      setPhase("error");
      setErrorMsg(err.message ?? "Failed to start pipeline");
    }
  }, [canExecute, query, readyFiles, maxIterations, guidelines, numStrategies, strategyMaxIters, numCodeVariants, numVerifiers]);

  // Poll execution status
  const { data: execStatus } = useQuery<ExecutionStatusResponse>({
    queryKey: ["ds-star-exec", executionId],
    queryFn: () => dsStarApi.getExecutionStatus(executionId!),
    enabled: !!executionId && phase === "running",
    refetchInterval: (q) => {
      const st = q.state.data?.status;
      if (st === "succeeded" || st === "failed" || st === "error") return false;
      return 2500;
    },
  });

  useEffect(() => {
    if (!execStatus) return;
    if (execStatus.status === "succeeded") {
      setPhase("completed");
      const resultCharts = (execStatus.result as any)?.charts;
      if (Array.isArray(resultCharts)) setCharts(resultCharts);
    } else if (execStatus.status === "failed" || execStatus.status === "error") {
      setPhase("error");
      setErrorMsg(execStatus.error ?? "Pipeline failed");
    }
    if (execStatus.run_id && !runId) {
      setRunId(execStatus.run_id);
    }
  }, [execStatus, runId]);

  // Poll DAG
  const dagQueryId = runId ?? workflowId;
  const { data: dagData, isLoading: dagLoading } = useQuery<WorkflowDAGLightweightResponse>({
    queryKey: ["ds-star-dag", dagQueryId],
    queryFn: () => getWorkflowDAGLightweight(dagQueryId!),
    enabled: !!dagQueryId,
    refetchInterval: (q) => {
      const st = q.state.data?.workflow_status;
      if (st === "running" || st === "pending") return 2500;
      return false;
    },
  });

  const phaseLabel: Record<PipelinePhase, string> = {
    idle: "Ready",
    uploading: "Uploading...",
    running: "Running...",
    completed: "Completed",
    error: "Error",
  };

  return (
    <div className="-m-4 sm:-m-6 flex flex-col" style={{ height: "calc(100vh - 4rem)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border/60 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-primary/10">
            <Microscope className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">DS Star</h1>
            <p className="text-xs text-muted-foreground">
              Data Science Agent — Iterative Planning & Verification
            </p>
          </div>
        </div>
        <Badge
          variant={
            phase === "completed"
              ? "success"
              : phase === "error"
                ? "destructive"
                : phase === "running"
                  ? "default"
                  : "secondary"
          }
        >
          {phase === "running" && (
            <Loader2 className="h-3 w-3 animate-spin mr-1" />
          )}
          {phaseLabel[phase]}
        </Badge>
      </div>

      {/* Main content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-0 h-full">
          {/* Left panel: config */}
          <div className="border-r border-border/60 overflow-y-auto p-5 space-y-5">
            {/* File Upload */}
            <Card variant="surface" interactive={false}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Data Files</CardTitle>
              </CardHeader>
              <CardContent>
                <FileUploadZone
                  files={files}
                  onFilesAdded={handleFilesAdded}
                  onRemove={handleRemoveFile}
                  disabled={phase === "running"}
                />
              </CardContent>
            </Card>

            {/* Query */}
            <Card variant="surface" interactive={false}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Query</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. Describe the key patterns in the data and create visualizations..."
                  disabled={phase === "running"}
                  rows={4}
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y disabled:opacity-50"
                />

                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                >
                  Advanced options
                  {showAdvanced ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                </button>

                {showAdvanced && (
                  <div className="space-y-3 pt-1">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">
                          Strategies ({numStrategies})
                        </label>
                        <input
                          type="range"
                          min={2}
                          max={5}
                          value={numStrategies}
                          onChange={(e) => setNumStrategies(parseInt(e.target.value))}
                          disabled={phase === "running"}
                          className="w-full accent-primary"
                        />
                        <div className="flex justify-between text-[10px] text-muted-foreground">
                          <span>2</span><span>5</span>
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">
                          Iters/Strategy ({strategyMaxIters})
                        </label>
                        <input
                          type="range"
                          min={3}
                          max={10}
                          value={strategyMaxIters}
                          onChange={(e) => setStrategyMaxIters(parseInt(e.target.value))}
                          disabled={phase === "running"}
                          className="w-full accent-primary"
                        />
                        <div className="flex justify-between text-[10px] text-muted-foreground">
                          <span>3</span><span>10</span>
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">
                          Code Variants ({numCodeVariants})
                        </label>
                        <input
                          type="range"
                          min={1}
                          max={5}
                          value={numCodeVariants}
                          onChange={(e) => setNumCodeVariants(parseInt(e.target.value))}
                          disabled={phase === "running"}
                          className="w-full accent-primary"
                        />
                        <div className="flex justify-between text-[10px] text-muted-foreground">
                          <span>1</span><span>5</span>
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">
                          Verifiers ({numVerifiers})
                        </label>
                        <input
                          type="range"
                          min={1}
                          max={5}
                          value={numVerifiers}
                          onChange={(e) => setNumVerifiers(parseInt(e.target.value))}
                          disabled={phase === "running"}
                          className="w-full accent-primary"
                        />
                        <div className="flex justify-between text-[10px] text-muted-foreground">
                          <span>1</span><span>5</span>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-md bg-muted/40 border border-border/40 px-3 py-2">
                      <p className="text-[10px] text-muted-foreground">
                        Est. AI calls: ~{Math.round(
                          30 + 1 + numStrategies * (1 + numCodeVariants + strategyMaxIters * (numVerifiers + 1 + 1 + numCodeVariants)) + 6 + 6 + 24 + 17 + 3
                        )}
                      </p>
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">
                        Max Iterations
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={maxIterations}
                        onChange={(e) =>
                          setMaxIterations(
                            Math.max(1, Math.min(50, parseInt(e.target.value) || 20))
                          )
                        }
                        disabled={phase === "running"}
                        className="w-full rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">
                        Guidelines (optional)
                      </label>
                      <textarea
                        value={guidelines}
                        onChange={(e) => setGuidelines(e.target.value)}
                        placeholder="Additional constraints or instructions..."
                        disabled={phase === "running"}
                        rows={2}
                        className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y disabled:opacity-50"
                      />
                    </div>
                  </div>
                )}

                <Button
                  onClick={handleExecute}
                  disabled={!canExecute}
                  className="w-full"
                  size="default"
                >
                  {phase === "running" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Running Pipeline...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      Execute Pipeline
                    </>
                  )}
                </Button>

                {errorMsg && (
                  <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-sm text-destructive">
                    {errorMsg}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Results */}
            {phase === "completed" && execStatus && (
              <Card variant="surface" interactive={false}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                    Results
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResultsPanel result={execStatus} charts={charts} />
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right panel: DAG + step detail */}
          <div className="flex flex-col overflow-hidden">
            {dagQueryId ? (
              <>
                <div className="flex-1 min-h-[400px]">
                  <WorkflowDAGViewer
                    workflowId={dagQueryId}
                    dagData={dagData}
                    loading={dagLoading}
                    onExecutionClick={(node) =>
                      setSelectedStepId(node.execution_id)
                    }
                    className="h-full"
                  />
                </div>

                {selectedStepId && (
                  <div className="border-t border-border/60 max-h-[45%] overflow-y-auto">
                    <div className="p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold">Step Detail</h3>
                        <button
                          onClick={() => setSelectedStepId(null)}
                          className="text-xs text-muted-foreground hover:text-foreground"
                        >
                          Close
                        </button>
                      </div>
                      <StepDetail executionId={selectedStepId} />
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center min-h-[400px] h-full text-muted-foreground">
                <div className="text-center space-y-2">
                  <Microscope className="h-12 w-12 mx-auto opacity-20" />
                  <p className="text-sm">
                    Upload data files and run a query to see the workflow DAG
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
